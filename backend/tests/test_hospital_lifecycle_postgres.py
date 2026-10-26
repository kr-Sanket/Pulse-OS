"""PostgreSQL integration tests for hospital verification lifecycle and audit logs (ADR-034).

**Opt-in.** Skipped unless ``PULSEOS_TEST_POSTGRES_URL`` names a PostgreSQL database
(``postgresql+asyncpg://…``) the suite may use. Point it at a scratch database, never at real data.

Covers:
- Alembic migration 0010: upgrade, constraints (PK, FKs, CHECK, Index), model parity, and downgrade.
- Foreign key and action check constraints enforced by PostgreSQL.
- Atomic commit of lifecycle transition and audit log in the same transaction.
- Audit write failure rolls back status mutation.
- Real PostgreSQL row-level locking (SELECT ... FOR UPDATE) serializing concurrent
  conflicting transitions.
- Idempotent retries do not create duplicate audit events.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from app.core.db import Base
from app.modules.auth.accounts import UserAccountService
from app.modules.auth.domain import Role
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.records.errors import InvalidHospitalStatusTransitionError
from app.modules.records.models import (
    Hospital,
    HospitalAuditLog,
    HospitalLifecycleAction,
    HospitalVerificationStatus,
)
from app.modules.records.organizations import HospitalService
from app.modules.records.repository import (
    DoctorRepository,
    HospitalAdminRepository,
    HospitalAuditLogRepository,
    HospitalRepository,
)
from app.shared.pagination import CursorKey
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

POSTGRES_URL = os.environ.get("PULSEOS_TEST_POSTGRES_URL", "")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL.startswith("postgresql"),
    reason="PostgreSQL tests are opt-in: set PULSEOS_TEST_POSTGRES_URL to a scratch database",
)

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _alembic_config(url: URL) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option(
        "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%")
    )
    return config


async def _admin_exec(statement: str) -> None:
    engine = create_async_engine(POSTGRES_URL, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(statement))
    finally:
        await engine.dispose()


@contextmanager
def _fresh_database() -> Iterator[URL]:
    name = f"pulseos_m34_mig_{uuid4().hex[:12]}"
    asyncio.run(_admin_exec(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(POSTGRES_URL).set(database=name)
    finally:
        asyncio.run(_admin_exec(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@asynccontextmanager
async def _scratch_schema() -> AsyncIterator[AsyncEngine]:
    schema = f"pulseos_m34_{uuid4().hex[:12]}"
    admin = create_async_engine(POSTGRES_URL)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        POSTGRES_URL, connect_args={"server_settings": {"search_path": schema}}
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield engine
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


class FakeAuthProvider:
    async def set_user_role(self, firebase_uid: str, role: Role) -> None:
        pass


def _service(session: AsyncSession) -> HospitalService:
    provider = FakeAuthProvider()
    accounts = UserAccountService(UserRepository(session), provider)  # type: ignore[arg-type]
    return HospitalService(
        accounts=accounts,
        hospitals=HospitalRepository(session),
        admins=HospitalAdminRepository(session),
        doctors=DoctorRepository(session),
        auditor=HospitalAuditLogRepository(session),
    )


def test_0010_postgres_migration_upgrade_constraints_and_downgrade() -> None:
    """Migration 0010 on real PostgreSQL creates table, constraints, index, matches models,
    and downgrades cleanly to 0009.
    """
    with _fresh_database() as url:
        config = _alembic_config(url)
        command.upgrade(config, "0010")

        async def inspect_db() -> tuple[set[tuple[str, str]], set[str], list[Any]]:
            engine = create_async_engine(url)
            try:
                async with engine.connect() as conn:
                    # 1. Constraints on hospital_audit_logs
                    res = await conn.execute(
                        text(
                            "select contype::text, conname from pg_constraint "
                            "where conrelid::regclass::text = 'hospital_audit_logs'"
                        )
                    )
                    constraints = {(row[0], row[1]) for row in res.tuples()}

                    # 2. Indexes on hospital_audit_logs
                    idx_res = await conn.execute(
                        text(
                            "select indexname from pg_indexes "
                            "where tablename = 'hospital_audit_logs'"
                        )
                    )
                    indexes = {row[0] for row in idx_res.tuples()}

                    # 3. Model parity check via Alembic compare_metadata
                    def _compare(sync_conn: Any) -> list[Any]:
                        ctx = MigrationContext.configure(sync_conn)
                        return list(compare_metadata(ctx, Base.metadata))

                    diff = await conn.run_sync(_compare)
                    return constraints, indexes, diff
            finally:
                await engine.dispose()

        constraints, indexes, diff = asyncio.run(inspect_db())

        expected_constraints = {
            ("p", "pk_hospital_audit_logs"),
            ("f", "fk_hospital_audit_logs_hospitals_hospital_id"),
            ("f", "fk_hospital_audit_logs_users_actor_user_id"),
            ("c", "ck_hospital_audit_logs_action_valid"),
        }
        assert expected_constraints.issubset(constraints)
        assert "ix_hospital_audit_logs_hospital_id_occurred_at_id" in indexes

        # Verify no schema drift between migration 0010 and mapped models
        # (ignoring unrelated legacy indices or pre-existing differences if any)
        table_diffs = [d for d in diff if getattr(d[1], "name", None) == "hospital_audit_logs"]
        assert table_diffs == []

        # Downgrade to 0009 drops hospital_audit_logs table and index
        command.downgrade(config, "0009")

        async def check_dropped() -> bool:
            engine = create_async_engine(url)
            try:
                async with engine.connect() as conn:
                    tables = await conn.execute(
                        text("select tablename from pg_tables where schemaname = 'public'")
                    )
                    return "hospital_audit_logs" in set(tables.scalars())
            finally:
                await engine.dispose()

        assert asyncio.run(check_dropped()) is False

        # Re-upgrade to head brings it back cleanly
        command.upgrade(config, "head")
        assert asyncio.run(check_dropped()) is True


def test_postgres_foreign_key_and_action_constraints() -> None:
    """PostgreSQL enforces foreign keys (no cascading delete) and action CHECK constraints."""

    async def scenario() -> None:
        async with _scratch_schema() as engine:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            h_id = uuid4()
            u_id = uuid4()

            async with factory() as session, session.begin():
                session.add(User(id=u_id, firebase_uid="fb-u1", role=Role.SYSTEM_ADMIN))
                session.add(
                    Hospital(
                        id=h_id,
                        hid="H-TEST1",
                        name="Test Hospital",
                        verification_status=HospitalVerificationStatus.PENDING,
                    )
                )

            # 1. Foreign key violation: non-existent hospital_id
            async with factory() as session:
                with pytest.raises(IntegrityError) as exc_info:
                    async with session.begin():
                        session.add(
                            HospitalAuditLog(
                                hospital_id=uuid4(),
                                actor_user_id=u_id,
                                action=HospitalLifecycleAction.VERIFIED,
                                occurred_at=datetime.now(UTC),
                            )
                        )
                # foreign_key_violation
                assert getattr(exc_info.value.orig, "sqlstate", None) == "23503"

            # 2. Foreign key violation: non-existent actor_user_id
            async with factory() as session:
                with pytest.raises(IntegrityError) as exc_info:
                    async with session.begin():
                        session.add(
                            HospitalAuditLog(
                                hospital_id=h_id,
                                actor_user_id=uuid4(),
                                action=HospitalLifecycleAction.VERIFIED,
                                occurred_at=datetime.now(UTC),
                            )
                        )
                assert getattr(exc_info.value.orig, "sqlstate", None) == "23503"

            # 3. Action CHECK constraint violation
            async with factory() as session:
                with pytest.raises(IntegrityError) as exc_info:
                    async with session.begin():
                        await session.execute(
                            text(
                                "INSERT INTO hospital_audit_logs "
                                "(id, hospital_id, actor_user_id, action, occurred_at) "
                                f"VALUES ('{uuid4()}', '{h_id}', '{u_id}', 'INVALID_ACTION', NOW())"
                            )
                        )
                assert getattr(exc_info.value.orig, "sqlstate", None) == "23514"  # check_violation

            # 4. Valid insert succeeds
            async with factory() as session, session.begin():
                audit_repo = HospitalAuditLogRepository(session)
                log = await audit_repo.record_lifecycle_event(
                    hospital_id=h_id,
                    actor_user_id=u_id,
                    action=HospitalLifecycleAction.VERIFIED,
                    reason="Audited by authority",
                )
                assert log.id is not None

    asyncio.run(scenario())


def test_postgres_successful_transition_and_audit_committed_atomically() -> None:
    """Status mutation and audit log row commit atomically in the shared transaction."""

    async def scenario() -> None:
        async with _scratch_schema() as engine:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            sys_admin_id = uuid4()
            h_id = uuid4()

            async with factory() as session, session.begin():
                session.add(
                    User(id=sys_admin_id, firebase_uid="fb-sys-atom", role=Role.SYSTEM_ADMIN)
                )
                session.add(
                    Hospital(
                        id=h_id,
                        hid="H-ATOM1",
                        name="Atomic Hospital",
                        verification_status=HospitalVerificationStatus.PENDING,
                    )
                )

            # Perform verification through service in a transaction
            async with factory() as session, session.begin():
                service = _service(session)
                hospital = await service.verify_hospital("H-ATOM1", verifier_user_id=sys_admin_id)
                assert hospital.verification_status is HospitalVerificationStatus.VERIFIED

            # Read back in a fresh session/transaction
            async with factory() as session:
                h = await HospitalRepository(session).get_by_hid("H-ATOM1")
                assert h is not None
                assert h.verification_status is HospitalVerificationStatus.VERIFIED
                assert h.verified_by_user_id == sys_admin_id
                assert h.verified_at is not None

                audit_logs = await HospitalAuditLogRepository(session).list_by_hospital_id(h_id)
                assert len(audit_logs) == 1
                assert audit_logs[0].action is HospitalLifecycleAction.VERIFIED
                assert audit_logs[0].actor_user_id == sys_admin_id
                assert audit_logs[0].hospital_id == h_id

    asyncio.run(scenario())


def test_postgres_audit_write_failure_rolls_back_status_mutation() -> None:
    """If the audit log write fails, the entire transaction rolls back cleanly."""

    class FailingAuditor:
        async def record_lifecycle_event(
            self,
            *,
            hospital_id: UUID,
            actor_user_id: UUID,
            action: HospitalLifecycleAction,
            reason: str | None = None,
        ) -> None:
            raise RuntimeError("Database connection interrupted during audit write")

        async def list_by_hospital_id(
            self,
            hospital_id: UUID,
            *,
            after: CursorKey | None = None,
            limit: int | None = None,
        ) -> list[HospitalAuditLog]:
            return []

    async def scenario() -> None:
        async with _scratch_schema() as engine:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            sys_admin_id = uuid4()
            h_id = uuid4()

            async with factory() as session, session.begin():
                session.add(
                    User(id=sys_admin_id, firebase_uid="fb-sys-fail-pg", role=Role.SYSTEM_ADMIN)
                )
                session.add(
                    Hospital(
                        id=h_id,
                        hid="H-FAIL1",
                        name="Fail Hospital",
                        verification_status=HospitalVerificationStatus.PENDING,
                    )
                )

            # Run transition with failing auditor in a transaction block
            async with factory() as session:
                service = HospitalService(
                    accounts=UserAccountService(UserRepository(session), FakeAuthProvider()),  # type: ignore[arg-type]
                    hospitals=HospitalRepository(session),
                    admins=HospitalAdminRepository(session),
                    doctors=DoctorRepository(session),
                    auditor=FailingAuditor(),
                )
                with pytest.raises(RuntimeError, match="Database connection interrupted"):
                    async with session.begin():
                        await service.verify_hospital("H-FAIL1", verifier_user_id=sys_admin_id)

            # Verify in fresh session: status is untouched PENDING, zero audit rows
            async with factory() as session:
                h = await HospitalRepository(session).get_by_hid("H-FAIL1")
                assert h is not None
                assert h.verification_status is HospitalVerificationStatus.PENDING
                assert h.verified_by_user_id is None
                assert h.verified_at is None

                logs = await HospitalAuditLogRepository(session).list_by_hospital_id(h_id)
                assert len(logs) == 0

    asyncio.run(scenario())


def test_postgres_concurrent_conflicting_transitions_serialized_by_row_lock() -> None:
    """Two concurrent transitions racing on separate connections are serialized by
    PostgreSQL's SELECT ... FOR UPDATE row-level locking. One wins, the second unblocks,
    detects the updated state, and raises InvalidHospitalStatusTransitionError.
    """

    async def scenario() -> None:
        async with _scratch_schema() as engine:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            admin_a = uuid4()
            admin_b = uuid4()
            h_id = uuid4()

            async with factory() as session, session.begin():
                session.add(User(id=admin_a, firebase_uid="fb-admin-a", role=Role.SYSTEM_ADMIN))
                session.add(User(id=admin_b, firebase_uid="fb-admin-b", role=Role.SYSTEM_ADMIN))
                session.add(
                    Hospital(
                        id=h_id,
                        hid="H-RACE1",
                        name="Race Hospital",
                        verification_status=HospitalVerificationStatus.PENDING,
                    )
                )

            barrier = asyncio.Barrier(2)

            async def attempt_verify() -> tuple[str, Any]:
                async with factory() as session:
                    await barrier.wait()
                    try:
                        async with session.begin():
                            service = _service(session)
                            await service.verify_hospital("H-RACE1", verifier_user_id=admin_a)
                        return "verify_success", None
                    except Exception as e:
                        return "verify_error", e

            async def attempt_reject() -> tuple[str, Any]:
                async with factory() as session:
                    await barrier.wait()
                    try:
                        async with session.begin():
                            service = _service(session)
                            await service.reject_hospital(
                                "H-RACE1", actor_user_id=admin_b, reason="Rejected"
                            )
                        return "reject_success", None
                    except Exception as e:
                        return "reject_error", e

            # Run concurrently on two independent connections
            result_v, result_r = await asyncio.gather(attempt_verify(), attempt_reject())

            statuses = {result_v[0], result_r[0]}
            # One must succeed, one must fail with InvalidHospitalStatusTransitionError
            assert ("verify_success" in statuses and "reject_error" in statuses) or (
                "reject_success" in statuses and "verify_error" in statuses
            )

            if "reject_error" in statuses:
                assert isinstance(result_r[1], InvalidHospitalStatusTransitionError)
                assert result_r[1].current_status is HospitalVerificationStatus.VERIFIED
                assert result_r[1].target_status is HospitalVerificationStatus.REJECTED
            else:
                assert isinstance(result_v[1], InvalidHospitalStatusTransitionError)
                assert result_v[1].current_status is HospitalVerificationStatus.REJECTED
                assert result_v[1].target_status is HospitalVerificationStatus.VERIFIED

            # Check final durable state in database: exactly 1 audit row, matching final status
            async with factory() as session:
                h = await HospitalRepository(session).get_by_hid("H-RACE1")
                assert h is not None
                logs = await HospitalAuditLogRepository(session).list_by_hospital_id(h_id)
                assert len(logs) == 1

                if h.verification_status is HospitalVerificationStatus.VERIFIED:
                    assert logs[0].action is HospitalLifecycleAction.VERIFIED
                    assert logs[0].actor_user_id == admin_a
                else:
                    assert h.verification_status is HospitalVerificationStatus.REJECTED
                    assert logs[0].action is HospitalLifecycleAction.REJECTED
                    assert logs[0].actor_user_id == admin_b

    asyncio.run(scenario())


def test_postgres_idempotent_retries_do_not_duplicate_audit_events() -> None:
    """Repeated transitions on PostgreSQL preserve idempotency without inserting duplicate
    audit log entries. Keyset ordering (occurred_at DESC, id DESC) functions correctly.
    """

    async def scenario() -> None:
        async with _scratch_schema() as engine:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            sys_admin_id = uuid4()
            h_id = uuid4()

            async with factory() as session, session.begin():
                session.add(
                    User(id=sys_admin_id, firebase_uid="fb-sys-idem", role=Role.SYSTEM_ADMIN)
                )
                session.add(
                    Hospital(
                        id=h_id,
                        hid="H-IDEM1",
                        name="Idempotent Hospital",
                        verification_status=HospitalVerificationStatus.PENDING,
                    )
                )

            # 1. PENDING -> VERIFIED
            async with factory() as session, session.begin():
                service = _service(session)
                await service.verify_hospital("H-IDEM1", verifier_user_id=sys_admin_id)

            # 2. VERIFIED -> VERIFIED (idempotent retry)
            async with factory() as session, session.begin():
                service = _service(session)
                await service.verify_hospital("H-IDEM1", verifier_user_id=sys_admin_id)

            async with factory() as session:
                logs = await HospitalAuditLogRepository(session).list_by_hospital_id(h_id)
                assert len(logs) == 1
                assert logs[0].action is HospitalLifecycleAction.VERIFIED

            # 3. VERIFIED -> SUSPENDED
            async with factory() as session, session.begin():
                service = _service(session)
                await service.suspend_hospital(
                    "H-IDEM1", actor_user_id=sys_admin_id, reason="Compliance audit"
                )

            # 4. SUSPENDED -> SUSPENDED (idempotent retry)
            async with factory() as session, session.begin():
                service = _service(session)
                await service.suspend_hospital("H-IDEM1", actor_user_id=sys_admin_id)

            async with factory() as session:
                logs = await HospitalAuditLogRepository(session).list_by_hospital_id(h_id)
                assert len(logs) == 2
                assert [log.action for log in logs] == [
                    HospitalLifecycleAction.SUSPENDED,
                    HospitalLifecycleAction.VERIFIED,
                ]

            # 5. SUSPENDED -> REINSTATED
            async with factory() as session, session.begin():
                service = _service(session)
                await service.reinstate_hospital(
                    "H-IDEM1", actor_user_id=sys_admin_id, reason="Compliance cleared"
                )

            # 6. VERIFIED -> VERIFIED (idempotent retry after reinstatement)
            async with factory() as session, session.begin():
                service = _service(session)
                await service.reinstate_hospital("H-IDEM1", actor_user_id=sys_admin_id)

            async with factory() as session:
                logs = await HospitalAuditLogRepository(session).list_by_hospital_id(h_id)
                assert len(logs) == 3
                assert [log.action for log in logs] == [
                    HospitalLifecycleAction.REINSTATED,
                    HospitalLifecycleAction.SUSPENDED,
                    HospitalLifecycleAction.VERIFIED,
                ]
                assert logs[0].reason == "Compliance cleared"
                assert logs[1].reason == "Compliance audit"
                assert logs[2].reason is None

    asyncio.run(scenario())


async def _seed_hospital(
    factory: async_sessionmaker[AsyncSession],
    *,
    hid: str,
    status: HospitalVerificationStatus,
    admin_ids: list[UUID],
) -> UUID:
    h_id = uuid4()
    async with factory() as session, session.begin():
        for admin_id in admin_ids:
            session.add(
                User(id=admin_id, firebase_uid=f"fb-{admin_id.hex}", role=Role.SYSTEM_ADMIN)
            )
        session.add(Hospital(id=h_id, hid=hid, name="Seeded", verification_status=status))
    return h_id


def test_postgres_real_audit_insert_failure_rolls_back_status_mutation() -> None:
    """A genuine database failure on the audit INSERT (FK violation: the actor is not a user)
    aborts the transition — the hospital row is unchanged and no audit row exists."""

    async def scenario() -> None:
        async with _scratch_schema() as engine:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            h_id = await _seed_hospital(
                factory, hid="H-FKF01", status=HospitalVerificationStatus.VERIFIED, admin_ids=[]
            )

            async with factory() as session:
                with pytest.raises(IntegrityError) as exc_info:
                    async with session.begin():
                        await _service(session).suspend_hospital(
                            "H-FKF01", actor_user_id=uuid4(), reason="ghost actor"
                        )
                assert getattr(exc_info.value.orig, "sqlstate", None) == "23503"

            async with factory() as session:
                h = await HospitalRepository(session).get_by_hid("H-FKF01")
                assert h is not None
                assert h.verification_status is HospitalVerificationStatus.VERIFIED
                assert await HospitalAuditLogRepository(session).list_by_hospital_id(h_id) == []

    asyncio.run(scenario())


def test_postgres_for_update_blocks_a_conflicting_transition_until_commit() -> None:
    """Deterministic lock proof: while transaction A holds the row lock (transition done, not
    yet committed), transaction B's conflicting transition is blocked; once A commits, B
    re-reads the committed status and is refused — B writes no audit event."""

    async def scenario() -> None:
        async with _scratch_schema() as engine:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            admin_a, admin_b = uuid4(), uuid4()
            h_id = await _seed_hospital(
                factory,
                hid="H-LOCK1",
                status=HospitalVerificationStatus.PENDING,
                admin_ids=[admin_a, admin_b],
            )

            a_transitioned = asyncio.Event()
            release_a = asyncio.Event()

            async def tx_a() -> None:
                async with factory() as session, session.begin():
                    await _service(session).verify_hospital("H-LOCK1", verifier_user_id=admin_a)
                    await session.flush()
                    a_transitioned.set()
                    await release_a.wait()

            async def tx_b() -> BaseException | None:
                await a_transitioned.wait()
                async with factory() as session:
                    try:
                        async with session.begin():
                            await _service(session).reject_hospital(
                                "H-LOCK1", actor_user_id=admin_b, reason="conflict"
                            )
                    except InvalidHospitalStatusTransitionError as exc:
                        return exc
                return None

            task_a = asyncio.create_task(tx_a())
            task_b = asyncio.create_task(tx_b())
            await a_transitioned.wait()
            # B must be parked on the row lock, not finished.
            done, _ = await asyncio.wait({task_b}, timeout=0.5)
            assert not done, "conflicting transition was not blocked by SELECT ... FOR UPDATE"

            release_a.set()
            await task_a
            outcome = await asyncio.wait_for(task_b, timeout=10)
            assert isinstance(outcome, InvalidHospitalStatusTransitionError)
            assert outcome.current_status is HospitalVerificationStatus.VERIFIED

            async with factory() as session:
                h = await HospitalRepository(session).get_by_hid("H-LOCK1")
                assert h is not None
                assert h.verification_status is HospitalVerificationStatus.VERIFIED
                logs = await HospitalAuditLogRepository(session).list_by_hospital_id(h_id)
                assert [(log.action, log.actor_user_id) for log in logs] == [
                    (HospitalLifecycleAction.VERIFIED, admin_a)
                ]

    asyncio.run(scenario())


def test_postgres_concurrent_identical_transitions_write_one_event() -> None:
    """Two administrators suspending the same hospital at once: both requests succeed
    (idempotent), and exactly one SUSPENDED event is written."""

    async def scenario() -> None:
        async with _scratch_schema() as engine:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            admin_a, admin_b = uuid4(), uuid4()
            h_id = await _seed_hospital(
                factory,
                hid="H-DUP01",
                status=HospitalVerificationStatus.VERIFIED,
                admin_ids=[admin_a, admin_b],
            )
            a_transitioned = asyncio.Event()
            release_a = asyncio.Event()

            async def suspend(actor: UUID, *, hold: bool) -> HospitalVerificationStatus:
                if not hold:
                    await a_transitioned.wait()
                async with factory() as session, session.begin():
                    hospital = await _service(session).suspend_hospital(
                        "H-DUP01", actor_user_id=actor
                    )
                    if hold:
                        await session.flush()
                        a_transitioned.set()
                        await release_a.wait()
                    return hospital.verification_status

            task_a = asyncio.create_task(suspend(admin_a, hold=True))
            task_b = asyncio.create_task(suspend(admin_b, hold=False))
            await a_transitioned.wait()
            await asyncio.sleep(0.3)  # let B reach (and park on) the row lock
            release_a.set()
            results = await asyncio.gather(task_a, task_b)
            assert list(results) == [HospitalVerificationStatus.SUSPENDED] * 2

            async with factory() as session:
                logs = await HospitalAuditLogRepository(session).list_by_hospital_id(h_id)
                assert [log.action for log in logs] == [HospitalLifecycleAction.SUSPENDED]

    asyncio.run(scenario())


def test_postgres_locked_read_refreshes_a_stale_identity_map_row() -> None:
    """A hospital already loaded in the session (e.g. by an earlier read in the same request)
    must not shadow the status read under FOR UPDATE: the transition decides on the committed
    row, not on the stale in-memory copy."""

    async def scenario() -> None:
        async with _scratch_schema() as engine:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            admin_a, admin_b = uuid4(), uuid4()
            h_id = await _seed_hospital(
                factory,
                hid="H-STALE",
                status=HospitalVerificationStatus.PENDING,
                admin_ids=[admin_a, admin_b],
            )

            async with factory() as session, session.begin():
                stale = await HospitalRepository(session).get_by_hid("H-STALE")
                assert stale is not None
                assert stale.verification_status is HospitalVerificationStatus.PENDING

                # Another administrator rejects it and commits meanwhile.
                async with factory() as other, other.begin():
                    await _service(other).reject_hospital("H-STALE", actor_user_id=admin_b)

                with pytest.raises(InvalidHospitalStatusTransitionError) as exc_info:
                    await _service(session).verify_hospital("H-STALE", verifier_user_id=admin_a)
                assert exc_info.value.current_status is HospitalVerificationStatus.REJECTED

            async with factory() as session:
                logs = await HospitalAuditLogRepository(session).list_by_hospital_id(h_id)
                assert [log.action for log in logs] == [HospitalLifecycleAction.REJECTED]

    asyncio.run(scenario())


# -- lock order: doctor activation / new consent requests vs. lifecycle transitions -------


async def _seed_staffed_hospital(
    factory: async_sessionmaker[AsyncSession], *, hid: str, doctors: int
) -> tuple[UUID, UUID, UUID, list[UUID]]:
    """A VERIFIED hospital with one HOSPITAL_ADMIN and ``doctors`` PENDING doctors.

    Returns (hospital id, system admin user id, hospital admin user id, doctor ids).
    """
    from app.modules.records.models import Doctor, HospitalAdmin

    h_id, sys_id, admin_id = uuid4(), uuid4(), uuid4()
    doctor_ids: list[UUID] = []
    async with factory() as session, session.begin():
        session.add(User(id=sys_id, firebase_uid=f"fb-{sys_id.hex}", role=Role.SYSTEM_ADMIN))
        session.add(User(id=admin_id, firebase_uid=f"fb-{admin_id.hex}", role=Role.HOSPITAL_ADMIN))
        session.add(
            Hospital(
                id=h_id,
                hid=hid,
                name="Seeded",
                verification_status=HospitalVerificationStatus.VERIFIED,
            )
        )
        await session.flush()
        session.add(HospitalAdmin(user_id=admin_id, hospital_id=h_id, full_name="Admin"))
        for n in range(doctors):
            user_id, doctor_id = uuid4(), uuid4()
            session.add(User(id=user_id, firebase_uid=f"fb-{user_id.hex}", role=Role.DOCTOR))
            await session.flush()
            session.add(
                Doctor(
                    id=doctor_id,
                    user_id=user_id,
                    hospital_id=h_id,
                    full_name=f"Dr {n}",
                    registration_number=f"R-{hid}-{n}",
                )
            )
            doctor_ids.append(doctor_id)
    return h_id, sys_id, admin_id, doctor_ids


async def _doctor_status(factory: async_sessionmaker[AsyncSession], doctor_id: UUID) -> str:
    async with factory() as session:
        doctor = await DoctorRepository(session).get_by_id(doctor_id)
        assert doctor is not None
        return doctor.status.value


def test_postgres_activation_waits_for_a_suspension_and_is_then_refused() -> None:
    """Suspension holds the hospital row (FOR UPDATE, not yet committed); an activation of
    that hospital's doctor must wait, then see SUSPENDED and fail — the doctor stays PENDING."""
    from app.modules.records.errors import HospitalNotVerifiedError
    from app.modules.records.models import DoctorStatus

    async def scenario() -> None:
        async with _scratch_schema() as engine:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            _, sys_id, admin_id, (doctor_id,) = await _seed_staffed_hospital(
                factory, hid="H-RACE1", doctors=1
            )
            suspended, release = asyncio.Event(), asyncio.Event()

            async def suspend() -> None:
                async with factory() as session, session.begin():
                    await _service(session).suspend_hospital(
                        "H-RACE1", actor_user_id=sys_id, reason="race"
                    )
                    await session.flush()
                    suspended.set()
                    await release.wait()

            async def activate() -> BaseException | None:
                await suspended.wait()
                async with factory() as session:
                    try:
                        async with session.begin():
                            await _service(session).set_doctor_status(
                                admin_id, doctor_id, DoctorStatus.ACTIVE
                            )
                    except HospitalNotVerifiedError as exc:
                        return exc
                return None

            task_s = asyncio.create_task(suspend())
            task_a = asyncio.create_task(activate())
            try:
                await suspended.wait()
                done, _ = await asyncio.wait({task_a}, timeout=0.5)
            finally:
                release.set()  # never leave the holder waiting, even when the check fails
            await task_s
            outcome = await asyncio.wait_for(task_a, timeout=10)
            assert not done, "activation was not blocked by the suspension's row lock"
            assert isinstance(outcome, HospitalNotVerifiedError)
            assert await _doctor_status(factory, doctor_id) == "PENDING"

    asyncio.run(scenario())


def test_postgres_suspension_waits_for_an_in_flight_activation() -> None:
    """The opposite interleaving: an activation holding the shared hospital lock commits
    first and the suspension then proceeds — both orders end consistent, neither deadlocks.
    A later activation is refused."""
    from app.modules.records.errors import HospitalNotVerifiedError
    from app.modules.records.models import DoctorStatus

    async def scenario() -> None:
        async with _scratch_schema() as engine:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            _, sys_id, admin_id, (first, second) = await _seed_staffed_hospital(
                factory, hid="H-RACE2", doctors=2
            )
            activated, release = asyncio.Event(), asyncio.Event()

            async def activate() -> None:
                async with factory() as session, session.begin():
                    await _service(session).set_doctor_status(admin_id, first, DoctorStatus.ACTIVE)
                    await session.flush()
                    activated.set()
                    await release.wait()

            async def suspend() -> None:
                await activated.wait()
                async with factory() as session, session.begin():
                    await _service(session).suspend_hospital(
                        "H-RACE2", actor_user_id=sys_id, reason="race"
                    )

            task_a = asyncio.create_task(activate())
            task_s = asyncio.create_task(suspend())
            try:
                await activated.wait()
                done, _ = await asyncio.wait({task_s}, timeout=0.5)
            finally:
                release.set()
            await asyncio.wait_for(asyncio.gather(task_a, task_s), timeout=10)
            assert not done, "suspension did not wait for the activation's shared lock"

            assert await _doctor_status(factory, first) == "ACTIVE"
            async with factory() as session:
                h = await HospitalRepository(session).get_by_hid("H-RACE2")
                assert h is not None
                assert h.verification_status is HospitalVerificationStatus.SUSPENDED
            async with factory() as session:
                with pytest.raises(HospitalNotVerifiedError):
                    async with session.begin():
                        await _service(session).set_doctor_status(
                            admin_id, second, DoctorStatus.ACTIVE
                        )
            assert await _doctor_status(factory, second) == "PENDING"
            # Deactivation stays available while suspended.
            async with factory() as session, session.begin():
                await _service(session).set_doctor_status(admin_id, first, DoctorStatus.DISABLED)
            assert await _doctor_status(factory, first) == "DISABLED"

    asyncio.run(scenario())


def test_postgres_concurrent_activations_do_not_block_each_other() -> None:
    """FOR SHARE is compatible with itself: two activations at one hospital both proceed."""
    from app.modules.records.models import DoctorStatus

    async def scenario() -> None:
        async with _scratch_schema() as engine:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            _, _, admin_id, (first, second) = await _seed_staffed_hospital(
                factory, hid="H-SHARE", doctors=2
            )
            first_done, release = asyncio.Event(), asyncio.Event()

            async def activate_first() -> None:
                async with factory() as session, session.begin():
                    await _service(session).set_doctor_status(admin_id, first, DoctorStatus.ACTIVE)
                    await session.flush()
                    first_done.set()
                    await release.wait()

            async def activate_second() -> None:
                await first_done.wait()
                async with factory() as session, session.begin():
                    await _service(session).set_doctor_status(admin_id, second, DoctorStatus.ACTIVE)

            task_1 = asyncio.create_task(activate_first())
            task_2 = asyncio.create_task(activate_second())
            try:
                await asyncio.wait_for(task_2, timeout=5)  # finishes while the first is open
            finally:
                release.set()
                await task_1
            assert await _doctor_status(factory, first) == "ACTIVE"
            assert await _doctor_status(factory, second) == "ACTIVE"

    asyncio.run(scenario())


def test_postgres_new_request_gate_waits_for_a_suspension() -> None:
    """The consent gate (``hospital_accepts_new_requests``) uses the same shared lock: it
    waits for an uncommitted suspension and then answers False."""
    from app.modules.records.directory import clinician_directory

    async def scenario() -> None:
        async with _scratch_schema() as engine:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            h_id, sys_id, _, _ = await _seed_staffed_hospital(factory, hid="H-RACE3", doctors=0)
            async with factory() as session:
                assert await clinician_directory(session).hospital_accepts_new_requests(h_id)
            suspended, release = asyncio.Event(), asyncio.Event()

            async def suspend() -> None:
                async with factory() as session, session.begin():
                    await _service(session).suspend_hospital("H-RACE3", actor_user_id=sys_id)
                    await session.flush()
                    suspended.set()
                    await release.wait()

            async def gate() -> bool:
                await suspended.wait()
                async with factory() as session, session.begin():
                    return await clinician_directory(session).hospital_accepts_new_requests(h_id)

            task_s = asyncio.create_task(suspend())
            task_g = asyncio.create_task(gate())
            try:
                await suspended.wait()
                done, _ = await asyncio.wait({task_g}, timeout=0.5)
            finally:
                release.set()
            await task_s
            accepted = await asyncio.wait_for(task_g, timeout=10)
            assert not done, "the request gate did not wait for the suspension's lock"
            assert accepted is False

    asyncio.run(scenario())
