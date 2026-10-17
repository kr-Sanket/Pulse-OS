"""HTTP tests for GET /api/v1/patients/lookup — the identity confirmation that guards a
hospital upload (docs/DOMAIN_MODEL.md §3 "existence + name confirmation only").

Real app, FakeAuthProvider, in-memory SQLite behind get_db_session. Every endpoint gets
its negative-authz tests (docs/DEVELOPMENT_GUIDE.md §Testing); this one additionally gets
a disclosure test, because the whole design of the response is what it leaves out.
"""

import re
from uuid import UUID

import pytest
from app.core.ratelimit import InMemoryRateLimiter
from app.modules.auth.domain import Role
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.models import User
from app.modules.patients.health_id import generate_health_id, is_valid_health_id
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.support import run_with_session

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


def _register_system_admin(
    db_engine: AsyncEngine,
    fake_auth: FakeAuthProvider,
    token: str = "sysadmin",
    firebase_uid: str = "fb-sysadmin",
) -> UUID:
    async def arrange(session: AsyncSession) -> UUID:
        user = User(firebase_uid=firebase_uid, role=Role.SYSTEM_ADMIN)
        session.add(user)
        await session.flush()
        return user.id

    user_id = run_with_session(db_engine, arrange)
    fake_auth.register_user(
        token, user_id=user_id, firebase_uid=firebase_uid, role=Role.SYSTEM_ADMIN
    )
    return user_id


def _refreshed(fake_auth: FakeAuthProvider, token: str, firebase_uid: str) -> dict[str, str]:
    """Headers for a token carrying the claims registration just provisioned."""
    fake_auth.register_token(
        f"{token}-refreshed",
        firebase_uid=firebase_uid,
        claims=fake_auth.custom_claims[firebase_uid],
    )
    return _bearer(f"{token}-refreshed")


def _register_hospital(
    client: TestClient, fake_auth: FakeAuthProvider, token: str, firebase_uid: str
) -> tuple[dict[str, str], str]:
    """Self-register a hospital (it starts PENDING); the admin's headers and its HID."""
    fake_auth.register_token(token, firebase_uid=firebase_uid, claims={})
    response = client.post(HOSPITAL_REGISTER, json=HOSPITAL_BODY, headers=_bearer(token))
    assert response.status_code == 201, response.text
    hid = response.json()["hospital"]["hid"]
    assert isinstance(hid, str)
    return _refreshed(fake_auth, token, firebase_uid), hid


@pytest.fixture
def admin_headers(
    client: TestClient, fake_auth: FakeAuthProvider, sqlite_db: None, db_engine: AsyncEngine
) -> dict[str, str]:
    """An administrator of a VERIFIED hospital — verified through the real
    SYSTEM_ADMIN endpoint, as the platform would."""
    headers, hid = _register_hospital(client, fake_auth, "admin", "fb-admin")
    _register_system_admin(db_engine, fake_auth, "sysadmin", "fb-sysadmin")
    verified = client.post(f"/api/v1/hospitals/{hid}/verify", headers=_bearer("sysadmin"))
    assert verified.status_code == 200, verified.text
    return headers


@pytest.fixture
def pending_admin_headers(
    client: TestClient, fake_auth: FakeAuthProvider, sqlite_db: None
) -> dict[str, str]:
    """An administrator of a self-registered hospital nobody has verified."""
    headers, _ = _register_hospital(client, fake_auth, "pending-admin", "fb-pending-admin")
    return headers


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
    client: TestClient, admin_headers: dict[str, str], sqlite_db: None
) -> None:
    """ADR-012's whole reason for a check character: a swap at the desk is caught before any
    database is consulted.

    Fixed inputs, not a freshly issued Health ID. An issued body is cryptographically random,
    so roughly one run in thirty-two drew one whose first two characters matched — the
    "transposition" was then a no-op and the test skipped itself, which is how the suite came
    to report a different number of executed tests run to run.

    ``PHI-IND-2026-7K3M99X`` is docs/DOMAIN_MODEL.md §4's canonical example and is genuinely
    valid; the two IDs below hold exactly the same characters in a different order, so the
    only thing separating them is the check character.
    """
    valid = "PHI-IND-2026-7K3M99X"
    transposed = "PHI-IND-2026-K73M99X"
    assert sorted(valid) == sorted(transposed), "these must differ only by a transposition"

    refused = client.get(LOOKUP, params={"healthId": transposed}, headers=admin_headers)

    assert refused.status_code == 422
    assert refused.json()["detail"] == "That is not a valid Pulse Health ID."

    # The untransposed ID passes validation and is refused for the other reason — no patient
    # holds it. Two different answers prove the check character discriminated, rather than
    # both IDs simply failing somewhere earlier.
    unswapped = client.get(LOOKUP, params={"healthId": valid}, headers=admin_headers)

    assert unswapped.status_code == 422
    assert unswapped.json()["detail"] == "No patient on PulseOS has that Health ID."


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


# -- hospital verification (amends ADR-021) --------------------------------------------


def test_a_pending_hospital_admin_cannot_resolve_a_health_id_to_a_name(
    client: TestClient, pending_admin_headers: dict[str, str], patient_health_id: str
) -> None:
    """Self-registration grants HOSPITAL_ADMIN at once; the name stays behind verification."""
    response = client.get(
        LOOKUP, params={"healthId": patient_health_id}, headers=pending_admin_headers
    )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "not verified" in response.json()["detail"]
    assert "Asha" not in response.text
    assert patient_health_id not in response.text


def test_a_pending_hospital_learns_nothing_about_which_health_ids_exist(
    client: TestClient, pending_admin_headers: dict[str, str], patient_health_id: str
) -> None:
    """Refused before the ID is parsed or resolved: an issued, an unissued and a malformed
    Health ID all receive the same answer."""
    answers = [
        client.get(LOOKUP, params={"healthId": health_id}, headers=pending_admin_headers)
        for health_id in (patient_health_id, _unissued_health_id(), "PHI-IND-2026-XXXXXXX")
    ]

    assert {response.status_code for response in answers} == {409}
    assert len({response.json()["detail"] for response in answers}) == 1


def test_the_same_admin_can_look_up_once_their_hospital_is_verified(
    client: TestClient, fake_auth: FakeAuthProvider, patient_health_id: str, db_engine: AsyncEngine
) -> None:
    headers, hid = _register_hospital(client, fake_auth, "late-admin", "fb-late-admin")
    params = {"healthId": patient_health_id}
    assert client.get(LOOKUP, params=params, headers=headers).status_code == 409

    _register_system_admin(db_engine, fake_auth, "sysadmin-2", "fb-sysadmin-2")
    verified = client.post(f"/api/v1/hospitals/{hid}/verify", headers=_bearer("sysadmin-2"))
    assert verified.status_code == 200, verified.text

    response = client.get(LOOKUP, params=params, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"healthId": patient_health_id, "fullName": "Asha Rao"}


def test_a_pending_hospital_lookup_still_spends_quota(
    client: TestClient,
    pending_admin_headers: dict[str, str],
    patient_health_id: str,
    rate_limiter: InMemoryRateLimiter,
) -> None:
    """The limiter runs before the verification gate, so refusals are throttled too."""
    limit = rate_limiter.limit_for("patient_lookup").limit
    _exhaust(client, pending_admin_headers, patient_health_id, limit)

    refused = client.get(
        LOOKUP, params={"healthId": patient_health_id}, headers=pending_admin_headers
    )
    assert refused.status_code == 429


# -- rate limiting (ADR-024, M3-D) -----------------------------------------------------------


def _exhaust(client: TestClient, headers: dict[str, str], health_id: str, times: int) -> None:
    for _ in range(times):
        client.get(LOOKUP, params={"healthId": health_id}, headers=headers)


def test_lookup_is_rate_limited_after_its_bucket_is_spent(
    client: TestClient,
    admin_headers: dict[str, str],
    patient_health_id: str,
    rate_limiter: InMemoryRateLimiter,
) -> None:
    limit = rate_limiter.limit_for("patient_lookup").limit
    _exhaust(client, admin_headers, patient_health_id, limit)

    refused = client.get(LOOKUP, params={"healthId": patient_health_id}, headers=admin_headers)

    assert refused.status_code == 429
    assert refused.headers["Retry-After"].isdigit()
    assert int(refused.headers["Retry-After"]) >= 1
    assert refused.headers["content-type"].startswith("application/problem+json")


def test_the_lookup_bucket_is_the_approved_twenty_per_minute(
    client: TestClient,
    admin_headers: dict[str, str],
    patient_health_id: str,
    rate_limiter: InMemoryRateLimiter,
) -> None:
    """Twenty succeed, the twenty-first does not."""
    assert rate_limiter.limit_for("patient_lookup").limit == 20
    _exhaust(client, admin_headers, patient_health_id, 19)

    assert (
        client.get(LOOKUP, params={"healthId": patient_health_id}, headers=admin_headers)
    ).status_code == 200
    assert (
        client.get(LOOKUP, params={"healthId": patient_health_id}, headers=admin_headers)
    ).status_code == 429


def test_a_rate_limited_lookup_reveals_nothing_about_the_health_id(
    client: TestClient,
    admin_headers: dict[str, str],
    patient_health_id: str,
    rate_limiter: InMemoryRateLimiter,
) -> None:
    """The invariant the limiter exists to preserve: once throttled, a Health ID that
    resolves and one that does not must be indistinguishable.

    Asserted semantically rather than byte-for-byte — status, title, detail, the presence of
    Retry-After, and the absence of any identifier or counter.
    """
    unissued = generate_health_id()
    _exhaust(client, admin_headers, patient_health_id, 20)

    real = client.get(LOOKUP, params={"healthId": patient_health_id}, headers=admin_headers)
    fake = client.get(LOOKUP, params={"healthId": unissued}, headers=admin_headers)

    assert real.status_code == fake.status_code == 429
    assert real.json()["title"] == fake.json()["title"]
    assert real.json()["detail"] == fake.json()["detail"]
    assert "Retry-After" in real.headers and "Retry-After" in fake.headers
    for response, health_id in ((real, patient_health_id), (fake, unissued)):
        body = response.text
        assert health_id not in body
        assert "Asha" not in body  # the patient's name never appears
        assert "patient_lookup" not in body  # nor the bucket
        assert "20" not in response.json()["detail"]  # nor any count


def test_the_limiter_does_not_disturb_authentication_or_authorization(
    client: TestClient, fake_auth: FakeAuthProvider, patient_health_id: str
) -> None:
    """401 and 403 still precede the limiter, so a refused caller spends no quota."""
    assert client.get(LOOKUP, params={"healthId": patient_health_id}).status_code == 401
    patient = _refreshed(fake_auth, "patient", "fb-patient")
    assert (
        client.get(LOOKUP, params={"healthId": patient_health_id}, headers=patient).status_code
        == 403
    )
