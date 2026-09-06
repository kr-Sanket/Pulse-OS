"""Tests for scripts/dev_link_identity.py — the seeded-identity linker.

The script deliberately lives outside ``app/`` and is imported by nothing in it
(.claude/TODO.md §1: it walks around ``auth/seed.py``'s guard against login-capable
seeded identities, so it must not be reachable from application code). That is why this
module loads it by file path rather than importing it: the isolation is the point, and a
package-level import would quietly undo it.

What is tested is what carries the risk — the environment gate, and the rules deciding
whether a given row may be rewritten at all. Both are pure.
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
from app.modules.auth.seed import get_or_create_synthetic_user

from tests.support import sqlite_session

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "dev_link_identity.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("dev_link_identity", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


linker = _load_script()


@dataclass
class FakeSettings:
    """Just the two fields the environment gate reads."""

    environment: str = "local"
    database_url: str = "postgresql+asyncpg://pulseos:pulseos@localhost:5432/pulseos"


def _user(firebase_uid: str, *, email: str = "admin.tmh@demo.pulseos.test") -> Any:
    return User(id=uuid4(), firebase_uid=firebase_uid, role=Role.HOSPITAL_ADMIN, email=email)


# -- the environment gate ---------------------------------------------------------------


def test_a_local_environment_on_a_local_database_is_allowed() -> None:
    linker.ensure_local_environment(FakeSettings())


@pytest.mark.parametrize("environment", ["test", "staging", "production"])
def test_every_environment_other_than_local_is_refused(environment: str) -> None:
    with pytest.raises(linker.UnsafeEnvironmentError):
        linker.ensure_local_environment(FakeSettings(environment=environment))


def test_a_remote_database_is_refused_even_when_the_environment_says_local() -> None:
    """The check that actually protects production. `Settings.environment` defaults to
    'local', so a deployment that forgot to set PULSEOS_ENVIRONMENT looks like a laptop —
    the database it points at does not."""
    remote = FakeSettings(
        database_url="postgresql+asyncpg://u:p@db.production.example.com:5432/pulseos"
    )

    with pytest.raises(linker.UnsafeEnvironmentError):
        linker.ensure_local_environment(remote)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "postgres"])
def test_developer_machine_hosts_are_recognised(host: str) -> None:
    assert linker.is_local_database(f"postgresql+asyncpg://u:p@{host}:5432/pulseos") is True


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://u:p@10.0.0.5:5432/pulseos",
        "postgresql+asyncpg://u:p@rds.amazonaws.com:5432/pulseos",
        "postgresql+asyncpg://u:p@localhost.evil.test:5432/pulseos",
    ],
)
def test_non_local_hosts_are_rejected(url: str) -> None:
    assert linker.is_local_database(url) is False


def test_the_driver_suffix_does_not_confuse_host_parsing() -> None:
    assert linker.database_host("postgresql+asyncpg://u:p@localhost:5432/db") == "localhost"
    assert linker.database_host("postgresql://u:p@localhost:5432/db") == "localhost"


def test_there_is_no_flag_that_bypasses_the_environment_gate() -> None:
    """A --force escape hatch must not exist: the gate is the whole safety property."""
    flags = {action.dest for action in linker.build_parser()._actions}

    assert "force" not in flags
    # --yes exists, but only skips the interactive prompt.
    assert "yes" in flags


# -- what may be rewritten ----------------------------------------------------------------


def test_a_seeded_identity_can_be_linked_to_a_real_uid() -> None:
    outcome = linker.plan_link(
        _user("synthetic:hospital-admin:hid-0001"), "3E6S9A89POfQmpXUTMsifUsLJcC2"
    )

    assert outcome.changed is True
    assert outcome.previous_uid == "synthetic:hospital-admin:hid-0001"
    assert outcome.new_uid == "3E6S9A89POfQmpXUTMsifUsLJcC2"


def test_running_again_with_the_same_uid_is_a_reported_no_op() -> None:
    """Repeatability, not a relink command: the same invocation twice must be safe."""
    outcome = linker.plan_link(_user("real-uid"), "real-uid")

    assert outcome.changed is False


def test_an_identity_already_owned_by_a_different_real_account_is_refused() -> None:
    """The dangerous case: silently reassigning somebody's real account to another UID."""
    with pytest.raises(linker.DevToolError, match="already linked"):
        linker.plan_link(_user("someone-elses-uid"), "my-uid")


def test_a_synthetic_subject_may_not_be_written_as_a_link() -> None:
    # Writing a synthetic subject would produce a row that can never sign in.
    with pytest.raises(linker.DevToolError):
        linker.plan_link(_user("synthetic:doctor:hid-0001"), "synthetic:something")


def test_an_empty_uid_is_refused() -> None:
    with pytest.raises(linker.DevToolError):
        linker.plan_link(_user("synthetic:doctor:hid-0001"), "")


def test_the_role_is_never_chosen_by_the_caller() -> None:
    """The outcome reports the row's existing role; there is no flag that sets one."""
    outcome = linker.plan_link(_user("synthetic:doctor:hid-0001"), "real")
    flags = {action.dest for action in linker.build_parser()._actions}

    assert outcome.role == str(Role.HOSPITAL_ADMIN)
    assert "role" not in flags


# -- resolution against a real schema --------------------------------------------------------


def test_resolve_target_finds_the_seeded_identity_by_email() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            await get_or_create_synthetic_user(
                session,
                firebase_uid="synthetic:hospital-admin:hid-0001",
                role=Role.HOSPITAL_ADMIN,
                email="admin.tmh@demo.pulseos.test",
            )

            found = await linker.resolve_target(session, "admin.tmh@demo.pulseos.test")

            assert found.firebase_uid == "synthetic:hospital-admin:hid-0001"

    asyncio.run(scenario())


def test_resolve_target_refuses_an_unknown_email() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            with pytest.raises(linker.DevToolError, match="No user"):
                await linker.resolve_target(session, "nobody@demo.pulseos.test")

    asyncio.run(scenario())


def test_listing_shows_only_identities_that_are_still_seeded() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            await get_or_create_synthetic_user(
                session,
                firebase_uid="synthetic:doctor:hid-0001",
                role=Role.DOCTOR,
                email="dr.verma@demo.pulseos.test",
            )
            session.add(
                User(firebase_uid="a-real-uid", role=Role.PATIENT, email="real@example.test")
            )
            await session.flush()

            linkable = await linker.find_seeded_identities(session)

            assert [user.email for user in linkable] == ["dr.verma@demo.pulseos.test"]

    asyncio.run(scenario())


def test_linking_rewrites_the_subject_and_leaves_everything_else_alone() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            seeded, _ = await get_or_create_synthetic_user(
                session,
                firebase_uid="synthetic:hospital-admin:hid-0001",
                role=Role.HOSPITAL_ADMIN,
                email="admin.tmh@demo.pulseos.test",
            )
            before_id, before_role = seeded.id, seeded.role

            outcome = linker.plan_link(seeded, "real-uid")
            await linker.apply_outcome(session, seeded, outcome, provision_claims=False)

            assert seeded.firebase_uid == "real-uid"
            # The identity itself is untouched: no new row, no role change.
            assert (seeded.id, seeded.role) == (before_id, before_role)
            assert seeded.email == "admin.tmh@demo.pulseos.test"

    asyncio.run(scenario())
