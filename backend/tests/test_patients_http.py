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


# -- PATCH /patients/me ------------------------------------------------------------------


def _registered(
    client: TestClient, fake_auth: FakeAuthProvider, token: str, *, uid: str = "fb-new"
) -> tuple[dict[str, object], str]:
    """Register, then mint a token carrying the claims registration provisioned.

    The signup token deliberately has no PulseOS claims — that is what makes it a signup
    token — so every authenticated call after registration needs the refreshed one, exactly
    as the browser does (``getIdToken(true)``). Returns the profile and that token.
    """
    response = client.post(REGISTER, json=BODY, headers=_bearer(token))
    assert response.status_code == 201, response.text
    refreshed = f"{token}-refreshed"
    fake_auth.register_token(refreshed, firebase_uid=uid, claims=fake_auth.custom_claims[uid])
    profile: dict[str, object] = response.json()
    return profile, refreshed


def test_a_partial_patch_changes_only_what_it_names(
    client: TestClient, fake_auth: FakeAuthProvider, signup_token: str
) -> None:
    before, token = _registered(client, fake_auth, signup_token)

    response = client.patch(ME, json={"fullName": "Asha Sharma"}, headers=_bearer(token))

    assert response.status_code == 200, response.text
    after = response.json()
    assert after["fullName"] == "Asha Sharma"
    assert after["dateOfBirth"] == before["dateOfBirth"]
    assert after["gender"] == before["gender"]
    assert after["healthId"] == before["healthId"]
    assert after["createdAt"] == before["createdAt"]
    # The response is the source of truth for the client, so it must match a fresh read.
    assert client.get(ME, headers=_bearer(token)).json() == after


def test_an_explicit_null_clears_a_nullable_field(
    client: TestClient, fake_auth: FakeAuthProvider, signup_token: str
) -> None:
    _, token = _registered(client, fake_auth, signup_token)

    response = client.patch(ME, json={"dateOfBirth": None, "gender": None}, headers=_bearer(token))

    assert response.status_code == 200, response.text
    assert response.json()["dateOfBirth"] is None
    assert response.json()["gender"] is None
    assert response.json()["fullName"] == "Asha Rao"


def test_an_empty_body_is_refused(
    client: TestClient, fake_auth: FakeAuthProvider, signup_token: str
) -> None:
    """Answering 200 would report an edit that never happened."""
    _, token = _registered(client, fake_auth, signup_token)
    assert client.patch(ME, json={}, headers=_bearer(token)).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"healthId": "PHI-IND-2026-1QE8DVR"},
        {"firebaseUid": "fb-someone-else"},
        {"role": "DOCTOR"},
        {"status": "SUSPENDED"},
        {"createdAt": "2020-01-01T00:00:00Z"},
        {"userId": "00000000-0000-4000-8000-000000000000"},
        {"fullName": "Asha", "healthId": "PHI-IND-2026-1QE8DVR"},
    ],
)
def test_immutable_and_unknown_fields_are_refused(
    client: TestClient, fake_auth: FakeAuthProvider, signup_token: str, body: dict[str, str]
) -> None:
    """Not silently ignored — a caller that thinks it changed its Health ID must be told
    otherwise. The last case proves one bad key poisons an otherwise valid edit."""
    before, token = _registered(client, fake_auth, signup_token)

    assert client.patch(ME, json=body, headers=_bearer(token)).status_code == 422
    assert client.get(ME, headers=_bearer(token)).json() == before


@pytest.mark.parametrize(
    "body",
    [
        {"fullName": ""},
        {"fullName": "   "},
        {"fullName": None},
        {"fullName": "x" * 121},
        {"dateOfBirth": "2099-01-01"},
        {"dateOfBirth": "not-a-date"},
        {"gender": "ROBOT"},
    ],
)
def test_validation_failures_are_422_and_write_nothing(
    client: TestClient, fake_auth: FakeAuthProvider, signup_token: str, body: dict[str, object]
) -> None:
    before, token = _registered(client, fake_auth, signup_token)

    assert client.patch(ME, json=body, headers=_bearer(token)).status_code == 422
    assert client.get(ME, headers=_bearer(token)).json() == before


def test_a_name_is_stored_trimmed(
    client: TestClient, fake_auth: FakeAuthProvider, signup_token: str
) -> None:
    _, token = _registered(client, fake_auth, signup_token)
    response = client.patch(ME, json={"fullName": "  Asha Rao  "}, headers=_bearer(token))
    assert response.json()["fullName"] == "Asha Rao"


def test_editing_requires_authentication_and_the_patient_role(
    client: TestClient, fake_auth: FakeAuthProvider, sqlite_db: None
) -> None:
    assert client.patch(ME, json={"fullName": "Nobody"}).status_code == 401

    fake_auth.register_token(
        "doctor",
        firebase_uid="fb-doctor",
        claims={ROLE_CLAIM: Role.DOCTOR.value, USER_ID_CLAIM: str(uuid4())},
    )
    assert client.patch(ME, json={"fullName": "N"}, headers=_bearer("doctor")).status_code == 403


def test_editing_without_a_profile_row_is_404(
    client: TestClient, fake_auth: FakeAuthProvider, sqlite_db: None
) -> None:
    """A token carrying PATIENT claims for a user that has no patient row — the same gap
    GET /me answers 404 for."""
    fake_auth.register_token(
        "ghost",
        firebase_uid="fb-ghost",
        claims={ROLE_CLAIM: Role.PATIENT.value, USER_ID_CLAIM: str(uuid4())},
    )
    assert client.patch(ME, json={"fullName": "Ghost"}, headers=_bearer("ghost")).status_code == 404


def test_one_patient_cannot_edit_another(
    client: TestClient, fake_auth: FakeAuthProvider, signup_token: str
) -> None:
    """There is no id in the path, so the only thing a second patient's token can reach is
    their own row."""
    first, first_token = _registered(client, fake_auth, signup_token)
    fake_auth.register_token("second", firebase_uid="fb-second", claims={"email": "b@example.test"})
    second = client.post(REGISTER, json={"fullName": "Bharat Singh"}, headers=_bearer("second"))
    assert second.status_code == 201
    fake_auth.register_token(
        "second-refreshed", firebase_uid="fb-second", claims=fake_auth.custom_claims["fb-second"]
    )

    hijack = client.patch(ME, json={"fullName": "Hijacked"}, headers=_bearer("second-refreshed"))
    assert hijack.status_code == 200
    assert hijack.json()["fullName"] == "Hijacked"  # their own row changed

    assert client.get(ME, headers=_bearer(first_token)).json() == first  # the other did not
