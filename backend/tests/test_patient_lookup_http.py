"""HTTP tests for GET /api/v1/patients/lookup — the identity confirmation that guards a
hospital upload (docs/DOMAIN_MODEL.md §3 "existence + name confirmation only").

Real app, FakeAuthProvider, in-memory SQLite behind get_db_session. Every endpoint gets
its negative-authz tests (docs/DEVELOPMENT_GUIDE.md §Testing); this one additionally gets
a disclosure test, because the whole design of the response is what it leaves out.
"""

import re

import pytest
from app.modules.auth.domain import Role
from app.modules.auth.fake import FakeAuthProvider
from app.modules.patients.health_id import generate_health_id, is_valid_health_id
from fastapi.testclient import TestClient

LOOKUP = "/api/v1/patients/lookup"
PATIENT_REGISTER = "/api/v1/patients/register"
HOSPITAL_REGISTER = "/api/v1/hospitals/register"

PATIENT_BODY = {"fullName": "Asha Rao", "dateOfBirth": "1990-05-01", "gender": "FEMALE"}
HOSPITAL_BODY = {
    "hospitalName": "Sunrise Clinic",
    "hospitalAddress": "Pune",
    "adminFullName": "Rita Admin",
}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _refreshed(fake_auth: FakeAuthProvider, token: str, firebase_uid: str) -> dict[str, str]:
    """Headers for a token carrying the claims registration just provisioned."""
    fake_auth.register_token(
        f"{token}-refreshed",
        firebase_uid=firebase_uid,
        claims=fake_auth.custom_claims[firebase_uid],
    )
    return _bearer(f"{token}-refreshed")


@pytest.fixture
def admin_headers(
    client: TestClient, fake_auth: FakeAuthProvider, sqlite_db: None
) -> dict[str, str]:
    fake_auth.register_token("admin", firebase_uid="fb-admin", claims={})
    response = client.post(HOSPITAL_REGISTER, json=HOSPITAL_BODY, headers=_bearer("admin"))
    assert response.status_code == 201, response.text
    return _refreshed(fake_auth, "admin", "fb-admin")


@pytest.fixture
def patient_health_id(client: TestClient, fake_auth: FakeAuthProvider, sqlite_db: None) -> str:
    fake_auth.register_token("patient", firebase_uid="fb-patient", claims={})
    response = client.post(PATIENT_REGISTER, json=PATIENT_BODY, headers=_bearer("patient"))
    assert response.status_code == 201, response.text
    health_id = response.json()["healthId"]
    assert isinstance(health_id, str)
    return health_id


def _unissued_health_id() -> str:
    """A well-formed Health ID (valid check character) that no patient holds.

    Drawn by the module's own generator rather than hand-built, so the test cannot drift
    from the checksum payload ADR-012 actually specifies."""
    candidate = generate_health_id()
    assert is_valid_health_id(candidate)
    return candidate


# -- the happy path -------------------------------------------------------------------


def test_hospital_admin_can_confirm_a_patient_by_health_id(
    client: TestClient, admin_headers: dict[str, str], patient_health_id: str
) -> None:
    response = client.get(LOOKUP, params={"healthId": patient_health_id}, headers=admin_headers)

    assert response.status_code == 200, response.text
    assert response.json() == {"healthId": patient_health_id, "fullName": "Asha Rao"}


def test_lookup_is_case_insensitive_and_echoes_the_canonical_id(
    client: TestClient, admin_headers: dict[str, str], patient_health_id: str
) -> None:
    # ADR-012 stores canonical uppercase; a reception desk types whatever it types.
    response = client.get(
        LOOKUP, params={"healthId": patient_health_id.lower()}, headers=admin_headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["healthId"] == patient_health_id


def test_the_query_bound_is_exactly_a_health_id(
    client: TestClient, admin_headers: dict[str, str], patient_health_id: str
) -> None:
    """`max_length=20` matches every sibling Health-ID surface, and a Health ID is exactly
    20 characters — so a padded value is refused at the boundary rather than trimmed. The
    portals normalise before sending, which is why this is a boundary fact worth pinning
    rather than a bug: a change here would silently diverge from four other endpoints."""
    response = client.get(
        LOOKUP, params={"healthId": f" {patient_health_id} "}, headers=admin_headers
    )

    assert response.status_code == 422


# -- the disclosure allow-list ---------------------------------------------------------


def test_response_carries_identity_confirmation_and_nothing_else(
    client: TestClient, admin_headers: dict[str, str], patient_health_id: str
) -> None:
    """The contract guard for the endpoint's whole purpose. The patient row holds a date of
    birth and a gender, and the response must not carry either."""
    body = client.get(LOOKUP, params={"healthId": patient_health_id}, headers=admin_headers).json()

    assert set(body) == {"healthId", "fullName"}
    leaked = {"dateOfBirth", "gender", "id", "userId", "patientId", "createdAt", "phone", "email"}
    assert leaked.isdisjoint(body)


def test_lookup_response_never_carries_the_internal_patient_uuid(
    client: TestClient, admin_headers: dict[str, str], patient_health_id: str
) -> None:
    raw = client.get(LOOKUP, params={"healthId": patient_health_id}, headers=admin_headers).text

    # The internal UUID never leaves the backend; the Health ID is the only identifier
    # a caller ever sees (docs/DOMAIN_MODEL.md rule 4).
    assert re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", raw) is None


# -- unknown and malformed Health IDs --------------------------------------------------


def test_a_well_formed_but_unissued_health_id_is_reported_as_no_such_patient(
    client: TestClient, admin_headers: dict[str, str], sqlite_db: None
) -> None:
    response = client.get(LOOKUP, params={"healthId": _unissued_health_id()}, headers=admin_headers)

    assert response.status_code == 422
    assert response.json()["detail"] == "No patient on PulseOS has that Health ID."


def test_a_malformed_health_id_is_refused_as_malformed_not_as_missing(
    client: TestClient, admin_headers: dict[str, str], sqlite_db: None
) -> None:
    """ADR-012's check character exists to catch a typo at the desk. Reporting a mistyped
    ID as "no such patient" would send the operator looking for the wrong problem."""
    response = client.get(
        LOOKUP, params={"healthId": "PHI-IND-2026-AAAAAAA"}, headers=admin_headers
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "That is not a valid Pulse Health ID."


def test_a_transposed_character_is_caught_offline_by_the_check_character(
    client: TestClient, admin_headers: dict[str, str], patient_health_id: str
) -> None:
    body = patient_health_id.removeprefix("PHI-IND-2026-")
    transposed = f"PHI-IND-2026-{body[1]}{body[0]}{body[2:]}"
    if transposed == patient_health_id:  # pragma: no cover - identical first two chars
        pytest.skip("this Health ID's first two characters are identical")

    response = client.get(LOOKUP, params={"healthId": transposed}, headers=admin_headers)

    assert response.status_code == 422
    assert response.json()["detail"] == "That is not a valid Pulse Health ID."


def test_a_missing_health_id_is_a_validation_error(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    assert client.get(LOOKUP, headers=admin_headers).status_code == 422


# -- authorization ---------------------------------------------------------------------


def test_lookup_requires_authentication(client: TestClient, sqlite_db: None) -> None:
    assert client.get(LOOKUP, params={"healthId": "PHI-IND-2026-7K3M99X"}).status_code == 401


def test_a_patient_may_not_look_up_other_patients(
    client: TestClient, fake_auth: FakeAuthProvider, patient_health_id: str
) -> None:
    # Enumeration is exactly what ADR-012's random Health IDs exist to prevent.
    headers = _refreshed(fake_auth, "patient", "fb-patient")

    response = client.get(LOOKUP, params={"healthId": patient_health_id}, headers=headers)

    assert response.status_code == 403


def test_a_doctor_may_not_use_the_hospital_lookup(
    client: TestClient, fake_auth: FakeAuthProvider, patient_health_id: str
) -> None:
    """Clinicians discover patients through /records/existence, which has its own
    disclosure contract; this endpoint returns a name and is not theirs."""
    fake_auth.register_token(
        "doc",
        firebase_uid="fb-doc",
        claims={"pulseos_role": Role.DOCTOR.value, "pulseos_user_id": "0" * 8},
    )

    assert client.get(
        LOOKUP, params={"healthId": patient_health_id}, headers=_bearer("doc")
    ).status_code in {403, 401}


def test_a_system_admin_may_not_look_up_a_patient(
    client: TestClient, fake_auth: FakeAuthProvider, patient_health_id: str
) -> None:
    """docs/SECURITY.md: platform operations never require patient identity."""
    fake_auth.register_token(
        "sys",
        firebase_uid="fb-sys",
        claims={"pulseos_role": Role.SYSTEM_ADMIN.value, "pulseos_user_id": "0" * 8},
    )

    assert client.get(
        LOOKUP, params={"healthId": patient_health_id}, headers=_bearer("sys")
    ).status_code in {403, 401}
