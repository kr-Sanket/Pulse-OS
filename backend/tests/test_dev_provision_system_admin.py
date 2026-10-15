"""Tests for scripts/dev_provision_system_admin.py.

Loads the script by path rather than package import to preserve the isolation rule
(scripts live outside app/ and must never be imported by application code).
"""

import asyncio
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

import pytest
from app.modules.auth.domain import Role
from app.modules.auth.models import User

from tests.support import sqlite_session

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "dev_provision_system_admin.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("dev_provision_system_admin", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


provisioner = _load_script()


@dataclass
class FakeSettings:
    environment: str = "local"
    database_url: str = "postgresql+asyncpg://pulseos:pulseos@localhost:5433/pulseos"


def _user(firebase_uid: str, role: Role, *, email: str = "user@example.test") -> Any:
    return User(id=uuid4(), firebase_uid=firebase_uid, role=role, email=email)


# -- Environment Gate -----------------------------------------------------------------


def test_a_local_environment_on_a_local_database_is_allowed() -> None:
    provisioner.ensure_local_environment(FakeSettings())


@pytest.mark.parametrize("environment", ["test", "staging", "production"])
def test_every_environment_other_than_local_is_refused(environment: str) -> None:
    with pytest.raises(provisioner.UnsafeEnvironmentError):
        provisioner.ensure_local_environment(FakeSettings(environment=environment))


def test_a_remote_database_is_refused_even_when_the_environment_says_local() -> None:
    remote = FakeSettings(
        database_url="postgresql+asyncpg://u:p@db.production.example.com:5432/pulseos"
    )
    with pytest.raises(provisioner.UnsafeEnvironmentError):
        provisioner.ensure_local_environment(remote)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "postgres"])
def test_developer_machine_hosts_are_recognised(host: str) -> None:
    assert provisioner.is_local_database(f"postgresql+asyncpg://u:p@{host}:5432/pulseos") is True


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://u:p@10.0.0.5:5432/pulseos",
        "postgresql+asyncpg://u:p@rds.amazonaws.com:5432/pulseos",
        "postgresql+asyncpg://u:p@localhost.evil.test:5432/pulseos",
    ],
)
def test_non_local_hosts_are_rejected(url: str) -> None:
    assert provisioner.is_local_database(url) is False


def test_there_is_no_flag_that_bypasses_the_environment_gate() -> None:
    flags = {action.dest for action in provisioner.build_parser()._actions}
    assert "force" not in flags
    assert "yes" in flags


# -- Input Validation -----------------------------------------------------------------


def test_an_empty_uid_is_refused() -> None:
    with pytest.raises(provisioner.DevToolError, match="required"):
        provisioner.clean_uid("")
    with pytest.raises(provisioner.DevToolError, match="required"):
        provisioner.clean_uid("   ")


def test_a_synthetic_subject_is_refused() -> None:
    with pytest.raises(provisioner.DevToolError, match="must be a real Firebase UID"):
        provisioner.clean_uid("synthetic:admin")


def test_valid_uid_is_stripped() -> None:
    assert provisioner.clean_uid("  fb-uid-123  ") == "fb-uid-123"


def test_blank_email_is_refused_if_supplied() -> None:
    with pytest.raises(provisioner.DevToolError, match="must not be blank"):
        provisioner.clean_email("   ")


def test_excessively_long_email_is_refused() -> None:
    with pytest.raises(provisioner.DevToolError, match="characters or fewer"):
        provisioner.clean_email("a" * 256 + "@example.test")


# -- Safety Invariants ----------------------------------------------------------------


def test_refuses_to_promote_hospital_admin_account() -> None:
    existing = _user("fb-admin", Role.HOSPITAL_ADMIN, email="admin@tmh.test")
    with pytest.raises(
        provisioner.DevToolError, match="already registered with role HOSPITAL_ADMIN"
    ):
        provisioner.plan_provision(existing, firebase_uid="fb-admin", email="admin@tmh.test")


def test_refuses_to_promote_doctor_account() -> None:
    existing = _user("fb-doc", Role.DOCTOR, email="doctor@tmh.test")
    with pytest.raises(provisioner.DevToolError, match="already registered with role DOCTOR"):
        provisioner.plan_provision(existing, firebase_uid="fb-doc", email="doctor@tmh.test")


def test_refuses_to_promote_patient_account() -> None:
    existing = _user("fb-pat", Role.PATIENT, email="patient@pulseos.test")
    with pytest.raises(provisioner.DevToolError, match="already registered with role PATIENT"):
        provisioner.plan_provision(existing, firebase_uid="fb-pat", email="patient@pulseos.test")


def test_plans_creation_for_new_firebase_uid() -> None:
    outcome = provisioner.plan_provision(
        None, firebase_uid="real-sysadmin-uid", email="sysadmin@pulseos.test"
    )
    assert outcome.created is True
    assert outcome.changed is True
    assert outcome.role == "SYSTEM_ADMIN"
    assert outcome.firebase_uid == "real-sysadmin-uid"
    assert outcome.email == "sysadmin@pulseos.test"


def test_idempotent_for_existing_system_admin() -> None:
    existing = _user("fb-sys", Role.SYSTEM_ADMIN, email="sys@pulseos.test")
    outcome = provisioner.plan_provision(existing, firebase_uid="fb-sys", email="sys@pulseos.test")
    assert outcome.created is False
    assert outcome.changed is False
    assert outcome.role == "SYSTEM_ADMIN"


def test_updates_email_for_existing_system_admin_if_changed() -> None:
    existing = _user("fb-sys", Role.SYSTEM_ADMIN, email="old@pulseos.test")
    outcome = provisioner.plan_provision(existing, firebase_uid="fb-sys", email="new@pulseos.test")
    assert outcome.created is False
    assert outcome.changed is True
    assert outcome.email == "new@pulseos.test"


# -- Persistence in DB ----------------------------------------------------------------


def test_apply_provision_creates_user_row_in_database() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            outcome = provisioner.plan_provision(
                None, firebase_uid="new-sys-uid", email="sysadmin@test.pulseos"
            )
            user = await provisioner.apply_provision(
                session, outcome, existing=None, provision_claims=False
            )

            assert user.firebase_uid == "new-sys-uid"
            assert user.role == Role.SYSTEM_ADMIN
            assert user.email == "sysadmin@test.pulseos"

    asyncio.run(scenario())


def test_apply_provision_updates_existing_sysadmin_in_database() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            initial = _user("existing-sys-uid", Role.SYSTEM_ADMIN, email="old@test.pulseos")
            session.add(initial)
            await session.flush()

            outcome = provisioner.plan_provision(
                initial, firebase_uid="existing-sys-uid", email="updated@test.pulseos"
            )
            user = await provisioner.apply_provision(
                session, outcome, existing=initial, provision_claims=False
            )

            assert user.email == "updated@test.pulseos"
            assert user.role == Role.SYSTEM_ADMIN

    asyncio.run(scenario())


def test_transaction_rolls_back_if_claim_provisioning_fails() -> None:
    from unittest.mock import patch

    from app.modules.auth.errors import AuthProviderUnavailableError
    from app.modules.auth.repository import UserRepository

    async def scenario() -> None:
        async with sqlite_session() as session:
            repo = UserRepository(session)
            outcome = provisioner.plan_provision(
                None, firebase_uid="failed-uid", email="failed@test.pulseos"
            )

            with pytest.raises(AuthProviderUnavailableError):
                async with session.begin_nested():
                    with patch(
                        "app.modules.auth.accounts.UserAccountService.provision_claims",
                        side_effect=AuthProviderUnavailableError("Firebase down"),
                    ):
                        await provisioner.apply_provision(
                            session, outcome, existing=None, provision_claims=True
                        )

            # Confirm rollback: no user exists with this UID
            found = await repo.get_by_firebase_uid("failed-uid")
            assert found is None

    asyncio.run(scenario())


def test_resolve_credentials_file_handles_none_and_relative_paths() -> None:
    from app.modules.auth.firebase import _resolve_credentials_file

    assert _resolve_credentials_file(None) is None
    assert _resolve_credentials_file("") is None

    # A non-existent path is returned as-is
    assert _resolve_credentials_file("nonexistent.json") == "nonexistent.json"
