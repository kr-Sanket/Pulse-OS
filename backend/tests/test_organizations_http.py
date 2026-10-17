"""HTTP tests for /api/v1/hospitals and /api/v1/doctors (M2 org management + RBAC).

Real app, FakeAuthProvider, in-memory SQLite behind get_db_session — request-scoped
transactions behave exactly as in production. Every endpoint gets its negative-authz
tests (docs/DEVELOPMENT_GUIDE.md §Testing).
"""

from uuid import UUID, uuid4

import pytest
from app.modules.auth.domain import Role
from app.modules.auth.errors import AuthProviderUnavailableError
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.models import User
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.support import run_with_session

HOSPITAL_REGISTER = "/api/v1/hospitals/register"
HOSPITAL_ME = "/api/v1/hospitals/me"
DOCTORS_REGISTER = "/api/v1/doctors/register"
DOCTORS_ME = "/api/v1/doctors/me"

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
    firebase_uid: str = "fb-sys",
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


@pytest.fixture
def admin_signup(fake_auth: FakeAuthProvider, sqlite_db: None) -> str:
    fake_auth.register_token(
        "admin-signup", firebase_uid="fb-admin", claims={"email": "admin@example.test"}
    )
    return "admin-signup"


def _register_admin(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    token: str,
    firebase_uid: str = "fb-admin",
) -> dict[str, str]:
    """Register a hospital+admin and return refreshed-claims headers for the admin."""
    response = client.post(HOSPITAL_REGISTER, json=HOSPITAL_BODY, headers=_bearer(token))
    assert response.status_code == 201, response.text
    fake_auth.register_token(
        f"{token}-refreshed",
        firebase_uid=firebase_uid,
        claims=fake_auth.custom_claims[firebase_uid],
    )
    return _bearer(f"{token}-refreshed")


def test_hospital_registration_end_to_end(
    client: TestClient, fake_auth: FakeAuthProvider, admin_signup: str
) -> None:
    response = client.post(HOSPITAL_REGISTER, json=HOSPITAL_BODY, headers=_bearer(admin_signup))
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"hospital", "adminFullName"}
    assert body["adminFullName"] == "Rita Admin"
    hospital = body["hospital"]
    assert hospital["verificationStatus"] == "PENDING"
    assert hospital["hid"].startswith("HID-") and len(hospital["hid"]) == 8
    assert fake_auth.custom_claims["fb-admin"]["pulseos_role"] == "HOSPITAL_ADMIN"

    repeat = client.post(HOSPITAL_REGISTER, json=HOSPITAL_BODY, headers=_bearer(admin_signup))
    assert repeat.status_code == 200
    assert repeat.json()["hospital"]["hid"] == hospital["hid"]


def test_hospital_registration_conflicts_with_existing_patient_role(
    client: TestClient, fake_auth: FakeAuthProvider, sqlite_db: None
) -> None:
    fake_auth.register_token("patient-signup", firebase_uid="fb-p", claims={})
    assert (
        client.post(
            "/api/v1/patients/register",
            json={"fullName": "P"},
            headers=_bearer("patient-signup"),
        ).status_code
        == 201
    )
    response = client.post(HOSPITAL_REGISTER, json=HOSPITAL_BODY, headers=_bearer("patient-signup"))
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")


def test_hospital_registration_is_atomic_when_claims_fail(
    client: TestClient, fake_auth: FakeAuthProvider, admin_signup: str
) -> None:
    fake_auth.set_claims_error = AuthProviderUnavailableError()
    assert (
        client.post(
            HOSPITAL_REGISTER, json=HOSPITAL_BODY, headers=_bearer(admin_signup)
        ).status_code
        == 503
    )
    fake_auth.set_claims_error = None
    retried = client.post(HOSPITAL_REGISTER, json=HOSPITAL_BODY, headers=_bearer(admin_signup))
    assert retried.status_code == 201  # nothing was persisted by the failed attempt


def test_hospitals_me_requires_the_hospital_admin_role(
    client: TestClient, fake_auth: FakeAuthProvider, sqlite_db: None
) -> None:
    fake_auth.register_user("pat", user_id=uuid4(), firebase_uid="fb-pat", role=Role.PATIENT)
    fake_auth.register_user("doc", user_id=uuid4(), firebase_uid="fb-doc", role=Role.DOCTOR)
    assert client.get(HOSPITAL_ME, headers=_bearer("pat")).status_code == 403
    assert client.get(HOSPITAL_ME, headers=_bearer("doc")).status_code == 403
    assert client.get(HOSPITAL_ME).status_code == 401


def test_hospitals_me_returns_own_hospital(
    client: TestClient, fake_auth: FakeAuthProvider, admin_signup: str
) -> None:
    headers = _register_admin(client, fake_auth, admin_signup)
    response = client.get(HOSPITAL_ME, headers=headers)
    assert response.status_code == 200
    assert response.json()["hospital"]["name"] == "Sunrise Clinic"


def test_verify_hospital_is_system_admin_only_and_idempotent(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    admin_signup: str,
    db_engine: AsyncEngine,
) -> None:
    admin_headers = _register_admin(client, fake_auth, admin_signup)
    hid = client.get(HOSPITAL_ME, headers=admin_headers).json()["hospital"]["hid"]

    # The hospital's own admin cannot self-verify (RBAC: System Admin verifies).
    assert client.post(f"/api/v1/hospitals/{hid}/verify", headers=admin_headers).status_code == 403

    # Other non-system-admin callers cannot verify (e.g. PATIENT, DOCTOR)
    fake_auth.register_user("pat", user_id=uuid4(), firebase_uid="fb-pat-verif", role=Role.PATIENT)
    assert client.post(f"/api/v1/hospitals/{hid}/verify", headers=_bearer("pat")).status_code == 403
    fake_auth.register_user("doc", user_id=uuid4(), firebase_uid="fb-doc-verif", role=Role.DOCTOR)
    assert client.post(f"/api/v1/hospitals/{hid}/verify", headers=_bearer("doc")).status_code == 403

    # First verification records administrator UUID and UTC timestamp
    sysadmin_1_id = _register_system_admin(db_engine, fake_auth, "sysadmin-1", "fb-sys-1")
    first = client.post(f"/api/v1/hospitals/{hid}/verify", headers=_bearer("sysadmin-1"))
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["verificationStatus"] == "VERIFIED"
    assert first_body["verifiedByUserId"] == str(sysadmin_1_id)
    assert first_body["verifiedAt"] is not None
    first_verified_at = first_body["verifiedAt"]

    # Repeated verification preserves original attribution (idempotent)
    _register_system_admin(db_engine, fake_auth, "sysadmin-2", "fb-sys-2")
    again = client.post(f"/api/v1/hospitals/{hid}/verify", headers=_bearer("sysadmin-2"))
    assert again.status_code == 200
    again_body = again.json()
    assert again_body["verificationStatus"] == "VERIFIED"
    assert again_body["verifiedByUserId"] == str(sysadmin_1_id)
    assert again_body["verifiedAt"] == first_verified_at

    missing = client.post("/api/v1/hospitals/HID-9999/verify", headers=_bearer("sysadmin-1"))
    assert missing.status_code == 404


def _verify(
    client: TestClient, fake_auth: FakeAuthProvider, hid: str, db_engine: AsyncEngine
) -> None:
    _register_system_admin(db_engine, fake_auth, "sysadmin", "fb-sys-shared")
    assert (
        client.post(f"/api/v1/hospitals/{hid}/verify", headers=_bearer("sysadmin")).status_code
        == 200
    )


def test_doctor_registration_and_management_flow(
    client: TestClient, fake_auth: FakeAuthProvider, admin_signup: str, db_engine: AsyncEngine
) -> None:
    admin_headers = _register_admin(client, fake_auth, admin_signup)
    hid = client.get(HOSPITAL_ME, headers=admin_headers).json()["hospital"]["hid"]

    # A PENDING hospital cannot take doctors.
    fake_auth.register_token("doc-signup", firebase_uid="fb-doc", claims={})
    doctor_body = {
        "fullName": "Dr. Meera",
        "specialty": "Cardiology",
        "registrationNumber": "MCI-1",
        "hospitalHid": hid,
    }
    blocked = client.post(DOCTORS_REGISTER, json=doctor_body, headers=_bearer("doc-signup"))
    assert blocked.status_code == 409

    _verify(client, fake_auth, hid, db_engine)

    created = client.post(DOCTORS_REGISTER, json=doctor_body, headers=_bearer("doc-signup"))
    assert created.status_code == 201
    assert created.json()["status"] == "PENDING"
    assert created.json()["hospital"]["hid"] == hid
    assert fake_auth.custom_claims["fb-doc"]["pulseos_role"] == "DOCTOR"

    repeat = client.post(DOCTORS_REGISTER, json=doctor_body, headers=_bearer("doc-signup"))
    assert repeat.status_code == 200

    unknown = client.post(
        DOCTORS_REGISTER,
        json={**doctor_body, "hospitalHid": "HID-9999"},
        headers=_bearer("doc-signup"),
    )
    assert unknown.status_code == 200  # idempotent short-circuit: already registered

    # The admin sees exactly their roster and can manage status.
    listing = client.get("/api/v1/hospitals/me/doctors", headers=admin_headers)
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert [d["fullName"] for d in items] == ["Dr. Meera"]
    doctor_id = items[0]["id"]

    activated = client.post(
        f"/api/v1/hospitals/me/doctors/{doctor_id}/activate", headers=admin_headers
    )
    assert activated.status_code == 200 and activated.json()["status"] == "ACTIVE"
    deactivated = client.post(
        f"/api/v1/hospitals/me/doctors/{doctor_id}/deactivate", headers=admin_headers
    )
    assert deactivated.status_code == 200 and deactivated.json()["status"] == "DISABLED"

    ghost = client.post(f"/api/v1/hospitals/me/doctors/{uuid4()}/activate", headers=admin_headers)
    assert ghost.status_code == 404

    # The doctor's own profile view works after a token refresh.
    fake_auth.register_token(
        "doc-refreshed", firebase_uid="fb-doc", claims=fake_auth.custom_claims["fb-doc"]
    )
    me = client.get(DOCTORS_ME, headers=_bearer("doc-refreshed"))
    assert me.status_code == 200
    assert me.json()["fullName"] == "Dr. Meera"


def test_doctor_registration_rejects_unknown_hospital_as_validation(
    client: TestClient, fake_auth: FakeAuthProvider, sqlite_db: None
) -> None:
    fake_auth.register_token("doc-signup", firebase_uid="fb-doc-2", claims={})
    response = client.post(
        DOCTORS_REGISTER,
        json={"fullName": "Dr. X", "registrationNumber": "R", "hospitalHid": "HID-4242"},
        headers=_bearer("doc-signup"),
    )
    assert response.status_code == 422


def test_doctor_endpoints_enforce_role_gates(
    client: TestClient, fake_auth: FakeAuthProvider, sqlite_db: None
) -> None:
    fake_auth.register_user("pat", user_id=uuid4(), firebase_uid="fb-pat", role=Role.PATIENT)
    # A patient can never touch hospital/doctor management surfaces (M2 gate criterion).
    assert client.get("/api/v1/hospitals/me/doctors", headers=_bearer("pat")).status_code == 403
    assert (
        client.post(
            f"/api/v1/hospitals/me/doctors/{uuid4()}/activate", headers=_bearer("pat")
        ).status_code
        == 403
    )
    assert client.get(DOCTORS_ME, headers=_bearer("pat")).status_code == 403


def test_unprovisioned_rows_yield_404_profiles(
    client: TestClient, fake_auth: FakeAuthProvider, sqlite_db: None
) -> None:
    # Claims say HOSPITAL_ADMIN/DOCTOR but no profile row exists (stale claims, wiped DB).
    fake_auth.register_user("adm", user_id=uuid4(), firebase_uid="fb-a", role=Role.HOSPITAL_ADMIN)
    fake_auth.register_user("doc", user_id=uuid4(), firebase_uid="fb-d", role=Role.DOCTOR)
    assert client.get(HOSPITAL_ME, headers=_bearer("adm")).status_code == 404
    assert client.get(DOCTORS_ME, headers=_bearer("doc")).status_code == 404


def test_list_hospitals_system_admin_only_and_filters(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    admin_signup: str,
    db_engine: AsyncEngine,
) -> None:
    # 1. Unauthenticated -> 401
    assert client.get("/api/v1/hospitals").status_code == 401

    # 2. Ordinary user (e.g. PATIENT, DOCTOR, HOSPITAL_ADMIN) -> 403
    fake_auth.register_user("pat", user_id=uuid4(), firebase_uid="fb-pat", role=Role.PATIENT)
    assert client.get("/api/v1/hospitals", headers=_bearer("pat")).status_code == 403

    admin_headers = _register_admin(client, fake_auth, admin_signup)
    assert client.get("/api/v1/hospitals", headers=admin_headers).status_code == 403

    # 3. System Admin -> 200
    sysadmin_id = _register_system_admin(db_engine, fake_auth, "sysadmin-list", "fb-sys-list")
    sys_headers = _bearer("sysadmin-list")

    # The registered hospital starts PENDING with null attribution
    all_res = client.get("/api/v1/hospitals", headers=sys_headers)
    assert all_res.status_code == 200
    data = all_res.json()
    assert "items" in data
    assert len(data["items"]) == 1
    hospital = data["items"][0]
    assert hospital["name"] == "Sunrise Clinic"
    assert hospital["verificationStatus"] == "PENDING"
    assert hospital["verifiedByUserId"] is None
    assert hospital["verifiedAt"] is None
    hid = hospital["hid"]

    # Filter ?status=PENDING -> returns 1
    pending_res = client.get("/api/v1/hospitals?status=PENDING", headers=sys_headers)
    assert pending_res.status_code == 200
    assert len(pending_res.json()["items"]) == 1

    # Filter ?status=VERIFIED -> returns 0
    verified_res = client.get("/api/v1/hospitals?status=VERIFIED", headers=sys_headers)
    assert verified_res.status_code == 200
    assert len(verified_res.json()["items"]) == 0

    # Verify hospital
    verify_res = client.post(f"/api/v1/hospitals/{hid}/verify", headers=sys_headers)
    assert verify_res.status_code == 200
    assert verify_res.json()["verificationStatus"] == "VERIFIED"
    assert verify_res.json()["verifiedByUserId"] == str(sysadmin_id)
    assert verify_res.json()["verifiedAt"] is not None

    # Now ?status=VERIFIED -> returns 1 with attribution
    verified_after = client.get("/api/v1/hospitals?status=VERIFIED", headers=sys_headers)
    assert verified_after.status_code == 200
    assert len(verified_after.json()["items"]) == 1
    item = verified_after.json()["items"][0]
    assert item["hid"] == hid
    assert item["verifiedByUserId"] == str(sysadmin_id)
    assert item["verifiedAt"] is not None

    # And ?status=PENDING -> returns 0
    pending_after = client.get("/api/v1/hospitals?status=PENDING", headers=sys_headers)
    assert pending_after.status_code == 200
    assert len(pending_after.json()["items"]) == 0
