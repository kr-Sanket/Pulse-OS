"""HTTP tests for /api/v1/patients: registration end-to-end and the profile endpoint.

Runs against the real app with FakeAuthProvider (conftest ``fake_auth``) and an
in-memory SQLite DB behind get_db_session (conftest ``sqlite_db``) — request-scoped
transactions behave exactly as in production, so atomicity is genuinely exercised.
"""

from uuid import UUID, uuid4

import pytest
from app.modules.auth.domain import Role
from app.modules.auth.errors import AuthProviderUnavailableError
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.service import ROLE_CLAIM, USER_ID_CLAIM
from app.modules.patients.health_id import is_valid_health_id
from fastapi.testclient import TestClient

REGISTER = "/api/v1/patients/register"
ME = "/api/v1/patients/me"

BODY = {"fullName": "Asha Rao", "dateOfBirth": "1990-05-01", "gender": "FEMALE"}


@pytest.fixture
def signup_token(fake_auth: FakeAuthProvider, sqlite_db: None) -> str:
    # A verified Firebase subject that has NOT registered yet: no PulseOS claims.
    fake_auth.register_token(
        "signup",
        firebase_uid="fb-new",
        claims={"phone_number": "+911234567890", "email": "asha@example.test"},
    )
    return "signup"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_successful_registration_returns_201_with_profile(
    client: TestClient, fake_auth: FakeAuthProvider, signup_token: str
) -> None:
    response = client.post(REGISTER, json=BODY, headers=_bearer(signup_token))
    assert response.status_code == 201
    profile = response.json()
    assert set(profile) == {"healthId", "fullName", "dateOfBirth", "gender", "createdAt"}
    assert is_valid_health_id(profile["healthId"])
    assert profile["fullName"] == "Asha Rao"
    assert profile["dateOfBirth"] == "1990-05-01"
    assert profile["gender"] == "FEMALE"

    claims = fake_auth.custom_claims["fb-new"]
    assert claims[ROLE_CLAIM] == "PATIENT"
    UUID(str(claims[USER_ID_CLAIM]))  # a real user id was provisioned


def test_duplicate_registration_returns_200_with_same_profile(
    client: TestClient, fake_auth: FakeAuthProvider, signup_token: str
) -> None:
    first = client.post(REGISTER, json=BODY, headers=_bearer(signup_token))
    second = client.post(REGISTER, json=BODY, headers=_bearer(signup_token))
    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["healthId"] == first.json()["healthId"]


def test_registration_requires_authentication(
    client: TestClient, fake_auth: FakeAuthProvider, sqlite_db: None
) -> None:
    assert client.post(REGISTER, json=BODY).status_code == 401


def test_registration_rejects_unknown_fields(
    client: TestClient, fake_auth: FakeAuthProvider, signup_token: str
) -> None:
    response = client.post(
        REGISTER, json={**BODY, "role": "SYSTEM_ADMIN"}, headers=_bearer(signup_token)
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "override",
    [
        {"fullName": "   "},  # blank name
        {"fullName": ""},
        {"dateOfBirth": "2999-01-01"},  # future date of birth
        {"gender": "ROBOT"},  # not in the vocabulary
    ],
)
def test_registration_validation_failures(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    signup_token: str,
    override: dict[str, str],
) -> None:
    response = client.post(REGISTER, json={**BODY, **override}, headers=_bearer(signup_token))
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_registration_is_atomic_when_claim_provisioning_fails(
    client: TestClient, fake_auth: FakeAuthProvider, signup_token: str
) -> None:
    fake_auth.set_claims_error = AuthProviderUnavailableError()
    failed = client.post(REGISTER, json=BODY, headers=_bearer(signup_token))
    assert failed.status_code == 503

    # Nothing was persisted: the retry takes the CREATE path (201), not the 200 path.
    fake_auth.set_claims_error = None
    retried = client.post(REGISTER, json=BODY, headers=_bearer(signup_token))
    assert retried.status_code == 201


def test_me_returns_profile_after_token_refresh(
    client: TestClient, fake_auth: FakeAuthProvider, signup_token: str
) -> None:
    created = client.post(REGISTER, json=BODY, headers=_bearer(signup_token))
    # Clients get the provisioned claims on their next token refresh — simulate it.
    fake_auth.register_token(
        "refreshed", firebase_uid="fb-new", claims=fake_auth.custom_claims["fb-new"]
    )
    response = client.get(ME, headers=_bearer("refreshed"))
    assert response.status_code == 200
    assert response.json() == created.json()


def test_me_requires_patient_role(
    client: TestClient, fake_auth: FakeAuthProvider, sqlite_db: None
) -> None:
    fake_auth.register_user("doc", user_id=uuid4(), firebase_uid="fb-doc", role=Role.DOCTOR)
    assert client.get(ME, headers=_bearer("doc")).status_code == 403


def test_me_is_404_when_profile_row_is_missing(
    client: TestClient, fake_auth: FakeAuthProvider, sqlite_db: None
) -> None:
    # Provisioned PATIENT claims but no patient row (e.g. wiped DB, stale claims).
    fake_auth.register_user("ghost", user_id=uuid4(), firebase_uid="fb-ghost", role=Role.PATIENT)
    response = client.get(ME, headers=_bearer("ghost"))
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
