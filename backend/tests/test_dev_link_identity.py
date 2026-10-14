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
    database_url: str = "postgresql+asyncpg://pulseos:pulseos@localhost:5433/pulseos"


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

            found = await linker.resolve_target(
                session, email="admin.tmh@demo.pulseos.test", firebase_uid=None
            )

            assert found.firebase_uid == "synthetic:hospital-admin:hid-0001"

    asyncio.run(scenario())


def test_resolve_target_refuses_an_unknown_email() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            with pytest.raises(linker.DevToolError, match="No user"):
                await linker.resolve_target(
                    session, email="nobody@demo.pulseos.test", firebase_uid=None
                )

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


# -- profile correction (HOSPITAL_ADMIN only) ------------------------------------------------


def _admin_user(firebase_uid: str = "real-uid") -> Any:
    return _user(firebase_uid)


def test_omitting_both_profile_flags_leaves_the_profile_alone() -> None:
    """The linker's existing behaviour must be untouched when no profile flags are given."""
    change = linker.plan_profile_sync(
        _admin_user(), "Ravi Prasad (Demo Admin)", full_name=None, email=None, firebase_uid="real"
    )

    assert change.changed is False
    assert change is linker.NO_PROFILE_CHANGE


def test_a_hospital_admin_profile_can_be_corrected() -> None:
    change = linker.plan_profile_sync(
        _admin_user(),
        "Ravi Prasad (Demo Admin)",
        full_name="Sanket Kumar",
        email="real@example.com",
        firebase_uid="real-uid",
    )

    assert change.changed is True
    assert change.full_name == "Sanket Kumar"
    assert change.email == "real@example.com"
    assert change.previous_full_name == "Ravi Prasad (Demo Admin)"


def test_profile_flags_without_a_firebase_uid_are_refused() -> None:
    """The rule that stops this being a profile editor: you cannot name a row and edit it."""
    with pytest.raises(linker.DevToolError, match="not a profile editor"):
        linker.plan_profile_sync(
            _admin_user(), "Ravi", full_name="Someone Else", email=None, firebase_uid=None
        )


@pytest.mark.parametrize("role", [Role.PATIENT, Role.DOCTOR, Role.SYSTEM_ADMIN])
def test_only_hospital_admin_profiles_may_be_corrected(role: Role) -> None:
    target = User(id=uuid4(), firebase_uid="real-uid", role=role, email="x@example.test")

    with pytest.raises(linker.DevToolError, match="HOSPITAL_ADMIN only"):
        linker.plan_profile_sync(
            target, "Whoever", full_name="New Name", email=None, firebase_uid="real-uid"
        )


def test_a_value_equal_to_the_stored_one_is_not_reported_as_a_change() -> None:
    target = _user("real-uid", email="real@example.com")

    change = linker.plan_profile_sync(
        target,
        "Sanket Kumar",
        full_name="Sanket Kumar",
        email="real@example.com",
        firebase_uid="real-uid",
    )

    assert change.changed is False


def test_blank_and_oversized_profile_values_are_refused() -> None:
    with pytest.raises(linker.DevToolError, match="must not be blank"):
        linker.plan_profile_sync(
            _admin_user(), "Ravi", full_name="   ", email=None, firebase_uid="real-uid"
        )
    with pytest.raises(linker.DevToolError, match="characters or fewer"):
        linker.plan_profile_sync(
            _admin_user(),
            "Ravi",
            full_name="x" * (linker.MAX_FULL_NAME_LENGTH + 1),
            email=None,
            firebase_uid="real-uid",
        )


def test_a_synthetic_identity_cannot_be_renamed_without_being_linked() -> None:
    """Seed data stays seed data: renaming requires supplying the real UID, and plan_link
    then refuses anything that is not an actual link."""
    seeded = _user("synthetic:hospital-admin:hid-0001")

    with pytest.raises(linker.DevToolError, match="not a profile editor"):
        linker.plan_profile_sync(
            seeded, "Ravi Prasad (Demo Admin)", full_name="Sanket", email=None, firebase_uid=None
        )


# -- profile correction against a real schema --------------------------------------------


async def _seed_linked_admin(
    session: Any, *, firebase_uid: str = "real-uid"
) -> tuple[Any, Any, Any]:
    """A hospital, its seeded admin profile, and that admin's user row already linked.

    Built through the module seeds so the shape matches production exactly, then linked
    the way the script links — which is the state the TMH row is actually in.
    """
    from app.modules.records.models import Hospital, HospitalAdmin, HospitalVerificationStatus

    hospital = Hospital(
        hid="HID-0001",
        name="TMH Jamshedpur",
        address="Jamshedpur",
        verification_status=HospitalVerificationStatus.VERIFIED,
    )
    session.add(hospital)
    await session.flush()

    user, _ = await get_or_create_synthetic_user(
        session,
        firebase_uid="synthetic:hospital-admin:hid-0001",
        role=Role.HOSPITAL_ADMIN,
        email="admin.tmh@demo.pulseos.test",
    )
    admin = HospitalAdmin(
        user_id=user.id, hospital_id=hospital.id, full_name="Ravi Prasad (Demo Admin)"
    )
    session.add(admin)
    await session.flush()

    user.firebase_uid = firebase_uid  # the link this tool performs
    await session.flush()
    return hospital, user, admin


def test_an_already_linked_identity_resolves_by_its_firebase_uid() -> None:
    """The TMH case: --user-email is no longer needed once the row carries a real UID."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            _, user, _ = await _seed_linked_admin(session)

            found = await linker.resolve_target(session, email=None, firebase_uid="real-uid")

            assert found.id == user.id

    asyncio.run(scenario())


def test_resolution_still_works_after_the_email_has_been_synchronised() -> None:
    """The footgun this design exists to avoid: the lookup key is also a mutable field."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            _, user, admin = await _seed_linked_admin(session)
            change = linker.plan_profile_sync(
                user,
                admin.full_name,
                full_name="Sanket Kumar",
                email="sanket@example.com",
                firebase_uid="real-uid",
            )
            await linker.apply_profile_change(session, user, admin, change)

            # The seeded email no longer names it, but the UID still does.
            by_uid = await linker.resolve_target(session, email=None, firebase_uid="real-uid")
            by_new_email = await linker.resolve_target(
                session, email="sanket@example.com", firebase_uid=None
            )

            assert by_uid.id == user.id == by_new_email.id

    asyncio.run(scenario())


def test_conflicting_email_and_uid_are_refused_rather_than_guessed() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            _, user, _ = await _seed_linked_admin(session)
            session.add(User(firebase_uid="other-uid", role=Role.PATIENT, email="other@x.test"))
            await session.flush()

            with pytest.raises(linker.DevToolError, match="two different identities"):
                await linker.resolve_target(
                    session, email="other@x.test", firebase_uid=user.firebase_uid
                )

    asyncio.run(scenario())


def test_an_email_belonging_to_another_user_is_detected() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            _, user, _ = await _seed_linked_admin(session)
            session.add(User(firebase_uid="other-uid", role=Role.PATIENT, email="taken@x.test"))
            await session.flush()

            taken = await linker.email_belongs_to_another_user(
                session, "taken@x.test", exclude_user_id=user.id
            )
            own = await linker.email_belongs_to_another_user(
                session, "admin.tmh@demo.pulseos.test", exclude_user_id=user.id
            )

            assert taken is True
            # The row's own email is not a collision with itself.
            assert own is False

    asyncio.run(scenario())


def test_correcting_the_profile_changes_two_columns_and_nothing_else() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            hospital, user, admin = await _seed_linked_admin(session)
            before = (
                user.id,
                user.role,
                user.firebase_uid,
                admin.hospital_id,
                hospital.verification_status,
                hospital.name,
            )

            change = linker.plan_profile_sync(
                user,
                admin.full_name,
                full_name="Sanket Kumar",
                email="sanket@example.com",
                firebase_uid="real-uid",
            )
            await linker.apply_profile_change(session, user, admin, change)

            assert admin.full_name == "Sanket Kumar"
            assert user.email == "sanket@example.com"
            # Role, hospital, verification and the Firebase UID are untouched.
            assert (
                user.id,
                user.role,
                user.firebase_uid,
                admin.hospital_id,
                hospital.verification_status,
                hospital.name,
            ) == before

    asyncio.run(scenario())


def test_the_correction_is_transactional_and_rolls_back_on_failure() -> None:
    """Claims are provisioned in the same transaction as the write, so a provider failure
    must undo the profile correction too — not leave a half-corrected row behind.

    Simulated by raising where ``provision_claims`` would raise: inside the transaction,
    after the profile has been flushed.
    """

    async def scenario() -> None:
        from app.core.db import Base
        from app.modules.records.models import HospitalAdmin
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from tests.support import create_sqlite_test_engine

        engine = create_sqlite_test_engine()
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            factory = async_sessionmaker(engine, expire_on_commit=False)

            async with factory() as session, session.begin():
                _, user, admin = await _seed_linked_admin(session)
                admin_id, user_id = admin.id, user.id

            with pytest.raises(RuntimeError, match="simulated provider failure"):
                async with factory() as session, session.begin():
                    user = await session.get(User, user_id)
                    admin = await session.get(HospitalAdmin, admin_id)
                    assert user is not None and admin is not None
                    change = linker.plan_profile_sync(
                        user,
                        admin.full_name,
                        full_name="Sanket Kumar",
                        email="sanket@example.com",
                        firebase_uid="real-uid",
                    )
                    await linker.apply_profile_change(session, user, admin, change)
                    raise RuntimeError("simulated provider failure")

            async with factory() as session:
                admin = await session.get(HospitalAdmin, admin_id)
                user = await session.get(User, user_id)
                assert admin is not None and user is not None
                assert admin.full_name == "Ravi Prasad (Demo Admin)"
                assert user.email == "admin.tmh@demo.pulseos.test"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_a_hospital_admin_without_a_profile_row_is_refused() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            user, _ = await get_or_create_synthetic_user(
                session,
                firebase_uid="synthetic:hospital-admin:hid-0009",
                role=Role.HOSPITAL_ADMIN,
                email="orphan@demo.pulseos.test",
            )

            with pytest.raises(linker.DevToolError, match="no hospital-admin profile"):
                await linker.load_admin_profile(session, user.id)

    asyncio.run(scenario())


def test_a_non_admin_is_told_the_real_reason_before_any_profile_row_is_looked_up() -> None:
    """Ordering matters for the message: a doctor has no hospital-admin row either, and
    reporting *that* would send a developer looking for a corrupt account instead of a
    capability that simply does not apply to them."""
    doctor = User(id=uuid4(), firebase_uid="real-uid", role=Role.DOCTOR, email="d@x.test")

    with pytest.raises(linker.DevToolError, match="HOSPITAL_ADMIN only"):
        linker.profile_sync_requested(doctor, full_name="Nope", email=None, firebase_uid="real-uid")


def test_no_profile_flags_means_no_sync_requested() -> None:
    assert (
        linker.profile_sync_requested(
            _admin_user(), full_name=None, email=None, firebase_uid="real-uid"
        )
        is False
    )


def test_a_uid_alone_is_enough_to_name_an_already_linked_row() -> None:
    """--user-email is optional once linked; requiring it would make the TMH case
    unreachable after --email has changed the address it would be named by."""
    assert linker.profile_sync_requested(
        _admin_user(), full_name="Sanket Kumar", email=None, firebase_uid="real-uid"
    )
