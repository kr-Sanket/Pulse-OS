"""HTTP-level auth tests: /api/v1/auth/me plus role gates on throwaway test routes.

Every failure must be an RFC 7807 problem (docs/API_GUIDELINES.md) and authn must run
before authz. The Firebase provider is replaced by FakeAuthProvider via the conftest
fixture — nothing here can contact Google.
"""

from typing import Annotated
from uuid import UUID, uuid4

import pytest
from app.modules.auth.dependencies import (
    RequireDoctor,
    RequireHospitalAdmin,
    RequirePatient,
    RequireSystemAdmin,
    require_role,
)
from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.auth.errors import (
    AuthProviderUnavailableError,
    ExpiredTokenError,
    RevokedTokenError,
    UserDisabledError,
)
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.models import User, UserStatus
from app.modules.auth.service import ROLE_CLAIM, USER_ID_CLAIM
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.support import run_with_session

ME = "/api/v1/auth/me"

gates = APIRouter(prefix="/gate")


@gates.get("/patient")
async def patient_gate(
    user: Annotated[AuthenticatedUser, Depends(RequirePatient)],
) -> dict[str, str]:
    return {"role": user.role.value}


@gates.get("/doctor")
async def doctor_gate(user: Annotated[AuthenticatedUser, Depends(RequireDoctor)]) -> dict[str, str]:
    return {"role": user.role.value}


@gates.get("/hospital-admin")
async def hospital_admin_gate(
    user: Annotated[AuthenticatedUser, Depends(RequireHospitalAdmin)],
) -> dict[str, str]:
    return {"role": user.role.value}


@gates.get("/system-admin")
async def system_admin_gate(
    user: Annotated[AuthenticatedUser, Depends(RequireSystemAdmin)],
) -> dict[str, str]:
    return {"role": user.role.value}


@gates.get("/clinical-staff")
async def clinical_staff_gate(
    user: Annotated[AuthenticatedUser, Depends(require_role(Role.DOCTOR, Role.HOSPITAL_ADMIN))],
) -> dict[str, str]:
    return {"role": user.role.value}


@pytest.fixture
def gated_client(app: FastAPI, client: TestClient) -> TestClient:
    app.include_router(gates)
    return client


@pytest.fixture(autouse=True)
def setup_db(sqlite_db: None) -> None:
    pass


def _register(
    db_engine: AsyncEngine,
    fake_auth: FakeAuthProvider,
    role: Role,
    token: str,
    *,
    status: UserStatus = UserStatus.ACTIVE,
    user_id: UUID | None = None,
) -> UUID:
    uid = user_id or uuid4()
    fake_auth.register_user(token, user_id=uid, firebase_uid=f"fb-{token}", role=role)

    async def _seed(session: AsyncSession) -> None:
        session.add(
            User(
                id=uid,
                firebase_uid=f"fb-{token}",
                role=role,
                status=status,
            )
        )

    run_with_session(db_engine, _seed)
    return uid


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- authentication via /auth/me ---


def test_missing_token_is_401_problem(client: TestClient, fake_auth: FakeAuthProvider) -> None:
    response = client.get(ME)
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["WWW-Authenticate"] == "Bearer"
    body = response.json()
    assert body["title"] == "Unauthorized"
    assert body["status"] == 401
    assert body["instance"] == ME


def test_malformed_header_is_401(client: TestClient, fake_auth: FakeAuthProvider) -> None:
    response = client.get(ME, headers={"Authorization": "Token abc"})
    assert response.status_code == 401
    assert "Bearer" in response.json()["detail"]


def test_invalid_token_is_401(client: TestClient, fake_auth: FakeAuthProvider) -> None:
    response = client.get(ME, headers=_bearer("never-registered"))
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid authentication token."


def test_expired_token_is_401(client: TestClient, fake_auth: FakeAuthProvider) -> None:
    fake_auth.register_error("old", ExpiredTokenError())
    response = client.get(ME, headers=_bearer("old"))
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication token has expired."
    assert 'error="invalid_token"' in response.headers["WWW-Authenticate"]


def test_revoked_token_is_401(client: TestClient, fake_auth: FakeAuthProvider) -> None:
    fake_auth.register_error("revoked", RevokedTokenError())
    response = client.get(ME, headers=_bearer("revoked"))
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication token has been revoked."
    assert 'error="invalid_token"' in response.headers["WWW-Authenticate"]


def test_user_disabled_is_401(client: TestClient, fake_auth: FakeAuthProvider) -> None:
    fake_auth.register_error("disabled", UserDisabledError())
    response = client.get(ME, headers=_bearer("disabled"))
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication token belongs to a disabled account."
    assert 'error="invalid_token"' in response.headers["WWW-Authenticate"]


def test_authenticated_request_returns_identity(
    client: TestClient, fake_auth: FakeAuthProvider, db_engine: AsyncEngine
) -> None:
    user_id = _register(db_engine, fake_auth, Role.PATIENT, "tok")
    response = client.get(ME, headers=_bearer("tok"))
    assert response.status_code == 200
    # camelCase on the wire (docs/API_GUIDELINES.md) — and nothing beyond the three fields.
    assert response.json() == {
        "userId": str(user_id),
        "firebaseUid": "fb-tok",
        "role": "PATIENT",
    }


def test_suspended_account_is_403(
    client: TestClient, fake_auth: FakeAuthProvider, db_engine: AsyncEngine
) -> None:
    _register(db_engine, fake_auth, Role.PATIENT, "suspended-tok", status=UserStatus.SUSPENDED)
    response = client.get(ME, headers=_bearer("suspended-tok"))
    assert response.status_code == 403
    assert response.json()["detail"] == "Account is suspended."


def test_missing_user_record_is_403(client: TestClient, fake_auth: FakeAuthProvider) -> None:
    fake_auth.register_user(
        "missing-tok",
        user_id=uuid4(),
        firebase_uid="fb-missing",
        role=Role.PATIENT,
    )
    response = client.get(ME, headers=_bearer("missing-tok"))
    assert response.status_code == 403
    assert response.json()["detail"] == "Account is not provisioned for PulseOS."


def test_unprovisioned_account_is_403(client: TestClient, fake_auth: FakeAuthProvider) -> None:
    fake_auth.register_token("fresh-signup", firebase_uid="fb-x", claims={})
    response = client.get(ME, headers=_bearer("fresh-signup"))
    assert response.status_code == 403
    assert response.json()["detail"] == "Account is not provisioned for PulseOS."


def test_forged_role_claim_is_403(client: TestClient, fake_auth: FakeAuthProvider) -> None:
    fake_auth.register_token(
        "forged",
        firebase_uid="fb-x",
        claims={ROLE_CLAIM: "SUPERUSER", USER_ID_CLAIM: str(uuid4())},
    )
    assert client.get(ME, headers=_bearer("forged")).status_code == 403


def test_mismatched_db_role_is_403(
    client: TestClient, fake_auth: FakeAuthProvider, db_engine: AsyncEngine
) -> None:
    user_id = uuid4()
    # Token claims DOCTOR, but DB user is PATIENT
    fake_auth.register_user(
        "mismatch-tok", user_id=user_id, firebase_uid="fb-mismatch", role=Role.DOCTOR
    )

    async def _seed(session: AsyncSession) -> None:
        session.add(
            User(
                id=user_id,
                firebase_uid="fb-mismatch",
                role=Role.PATIENT,
                status=UserStatus.ACTIVE,
            )
        )

    run_with_session(db_engine, _seed)
    response = client.get(ME, headers=_bearer("mismatch-tok"))
    assert response.status_code == 403
    assert response.json()["detail"] == "Account is not provisioned for PulseOS."


def test_provider_unavailable_is_503(client: TestClient, fake_auth: FakeAuthProvider) -> None:
    fake_auth.register_error("tok", AuthProviderUnavailableError())
    response = client.get(ME, headers=_bearer("tok"))
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")


# --- role gates (ADR-013 layer 1) ---


def test_matching_role_passes_gate(
    gated_client: TestClient, fake_auth: FakeAuthProvider, db_engine: AsyncEngine
) -> None:
    for role, path in [
        (Role.PATIENT, "/gate/patient"),
        (Role.DOCTOR, "/gate/doctor"),
        (Role.HOSPITAL_ADMIN, "/gate/hospital-admin"),
        (Role.SYSTEM_ADMIN, "/gate/system-admin"),
    ]:
        _register(db_engine, fake_auth, role, f"tok-{role}")
        response = gated_client.get(path, headers=_bearer(f"tok-{role}"))
        assert response.status_code == 200, (role, path)
        assert response.json() == {"role": role.value}


def test_wrong_role_is_403(
    gated_client: TestClient, fake_auth: FakeAuthProvider, db_engine: AsyncEngine
) -> None:
    _register(db_engine, fake_auth, Role.DOCTOR, "doc")
    response = gated_client.get("/gate/patient", headers=_bearer("doc"))
    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient role for this operation."


def test_multi_role_gate(
    gated_client: TestClient, fake_auth: FakeAuthProvider, db_engine: AsyncEngine
) -> None:
    _register(db_engine, fake_auth, Role.DOCTOR, "doc")
    _register(db_engine, fake_auth, Role.HOSPITAL_ADMIN, "adm")
    _register(db_engine, fake_auth, Role.PATIENT, "pat")
    assert gated_client.get("/gate/clinical-staff", headers=_bearer("doc")).status_code == 200
    assert gated_client.get("/gate/clinical-staff", headers=_bearer("adm")).status_code == 200
    assert gated_client.get("/gate/clinical-staff", headers=_bearer("pat")).status_code == 403


def test_system_admin_is_blocked_from_clinical_gates(
    gated_client: TestClient, fake_auth: FakeAuthProvider, db_engine: AsyncEngine
) -> None:
    # ADR-013 invariant: SYSTEM_ADMIN is never granted clinical/PHI-facing roles.
    _register(db_engine, fake_auth, Role.SYSTEM_ADMIN, "sys")
    for path in ["/gate/patient", "/gate/doctor", "/gate/hospital-admin", "/gate/clinical-staff"]:
        assert gated_client.get(path, headers=_bearer("sys")).status_code == 403, path


def test_gate_rejects_suspended_user(
    gated_client: TestClient, fake_auth: FakeAuthProvider, db_engine: AsyncEngine
) -> None:
    for role, path in [
        (Role.PATIENT, "/gate/patient"),
        (Role.DOCTOR, "/gate/doctor"),
        (Role.HOSPITAL_ADMIN, "/gate/hospital-admin"),
        (Role.SYSTEM_ADMIN, "/gate/system-admin"),
    ]:
        token = f"susp-{role}"
        _register(db_engine, fake_auth, role, token, status=UserStatus.SUSPENDED)
        response = gated_client.get(path, headers=_bearer(token))
        assert response.status_code == 403, (role, path)
        assert response.json()["detail"] == "Account is suspended."


def test_gate_rejects_missing_user_record(
    gated_client: TestClient, fake_auth: FakeAuthProvider
) -> None:
    for role, path in [
        (Role.PATIENT, "/gate/patient"),
        (Role.DOCTOR, "/gate/doctor"),
        (Role.HOSPITAL_ADMIN, "/gate/hospital-admin"),
        (Role.SYSTEM_ADMIN, "/gate/system-admin"),
    ]:
        token = f"missing-{role}"
        fake_auth.register_user(token, user_id=uuid4(), firebase_uid=f"fb-{token}", role=role)
        response = gated_client.get(path, headers=_bearer(token))
        assert response.status_code == 403, (role, path)
        assert response.json()["detail"] == "Account is not provisioned for PulseOS."


def test_gate_without_token_is_401_not_403(
    gated_client: TestClient, fake_auth: FakeAuthProvider
) -> None:
    # Authentication runs before authorization.
    assert gated_client.get("/gate/patient").status_code == 401


def test_require_role_rejects_empty_role_list() -> None:
    with pytest.raises(ValueError, match="at least one role"):
        require_role()
