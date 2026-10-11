"""PostgreSQL-specific batch sealing behaviour (ADR-027 risks: concurrency and ordering).

**Opt-in.** Skipped unless ``PULSEOS_TEST_POSTGRES_URL`` names a PostgreSQL database
(``postgresql+asyncpg://…``) the suite may use. Each run creates its own uniquely named
schema, works only inside it and drops only that schema afterwards; nothing outside it is
read or written. Point it at a scratch database, never at real data.

What SQLite cannot show and these do: two sealers on separate connections racing for real
(the advisory lock and the UNIQUE constraints together), PostgreSQL's ``uuid`` ordering
agreeing with Python's canonical order, and ``timestamptz`` round-trips.
"""

import asyncio
import datetime as dt
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from app.core.db import Base
from app.modules.auth.domain import Role
from app.modules.auth.models import User
from app.modules.consent.batch_service import AuditBatchService
from app.modules.consent.errors import BatchSealConflictError, BatchSealIntegrityError
from app.modules.consent.models import AuditAction, AuditBatch, AuditBatchMember, AuditLog
from app.modules.consent.repository import (
    AuditBatchRepository,
    IntegrityViolation,
    classify_integrity_error,
)
from app.modules.consent.service import HASH_SCHEME_V3, recompute_event_hash
from app.modules.patients.models import Patient
from sqlalchemy import func, select, text
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

BASE = dt.datetime(2026, 10, 11, 9, 0, tzinfo=dt.UTC)


@asynccontextmanager
async def _scratch_schema() -> AsyncIterator[AsyncEngine]:
    schema = f"pulseos_m63_{uuid4().hex[:12]}"
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


async def _seed(engine: AsyncEngine, occurred: list[dt.datetime], ids: list[UUID]) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        user = User(firebase_uid=f"fb-{uuid4()}", role=Role.PATIENT)
        session.add(user)
        await session.flush()
        patient = Patient(user_id=user.id, health_id="PHI-IND-2026-1QE8DVR", full_name="P")
        session.add(patient)
        await session.flush()
        for event_id, at in zip(ids, occurred, strict=True):
            event = AuditLog(
                id=event_id,
                actor_user_id=user.id,
                actor_role=Role.PATIENT,
                action=AuditAction.RECORD_VIEWED,
                patient_id=patient.id,
                request_context=None,
                occurred_at=at,
                actor_hospital_id=None,
                hash_version=HASH_SCHEME_V3,
                event_hash="",
            )
            event.event_hash = recompute_event_hash(event)
            session.add(event)


#: Consecutive conflicts one sealer tolerates before failing the test. A conflict means another
#: sealer committed first, so under normal contention this sealer either wins soon or finds
#: nothing left; only a collision that recurs on every attempt (e.g. a constraint the sealer can
#: never satisfy) reaches the cap. Generous on purpose: with the advisory lock, conflicts are
#: expected to be rare or absent.
MAX_CONSECUTIVE_CONFLICTS = 100


async def _seal_until_done(engine: AsyncEngine, max_size: int) -> int:
    """One sealer: its own connection, one transaction per batch, retry on conflict.

    Each attempt opens a fresh session and transaction; leaving ``session.begin()`` on an
    exception rolls back and releases the advisory lock. Retries are bounded: a persistent
    conflict fails the test with context instead of hanging the run.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    sealed = 0
    consecutive_conflicts = 0
    while True:
        async with factory() as session:
            service = AuditBatchService(
                batches=AuditBatchRepository(session),
                max_size=max_size,
                backlog_threshold=dt.timedelta(seconds=900),
            )
            try:
                async with session.begin():
                    batch = await service.seal_next_batch()
            except BatchSealConflictError as conflict:
                consecutive_conflicts += 1
                if consecutive_conflicts >= MAX_CONSECUTIVE_CONFLICTS:
                    # Counts and the exception type only — no constraint values, digests or ids.
                    cause = type(conflict.__cause__).__name__
                    raise AssertionError(
                        f"sealer gave up after {consecutive_conflicts} consecutive "
                        f"BatchSealConflictError (cause: {cause}); it had sealed {sealed} "
                        f"batch(es) with max_size={max_size}. A conflict that recurs on every "
                        "attempt suggests a constraint the sealer can never satisfy (for "
                        "example a colliding commitment), not ordinary contention."
                    ) from conflict
                continue
            consecutive_conflicts = 0
            if batch is None:
                return sealed
            sealed += 1


def test_concurrent_sealers_batch_every_event_exactly_once() -> None:
    async def scenario() -> None:
        async with _scratch_schema() as engine:
            ids = [uuid4() for _ in range(40)]
            await _seed(engine, [BASE + dt.timedelta(seconds=i) for i in range(40)], ids)

            counts = await asyncio.gather(*(_seal_until_done(engine, 7) for _ in range(4)))

            factory = async_sessionmaker(engine)
            async with factory() as session:
                numbers = (await session.execute(select(AuditBatch.batch_number))).scalars()
                members = (await session.execute(select(AuditBatchMember))).scalars().all()
                report = await AuditBatchService(
                    batches=AuditBatchRepository(session),
                    max_size=7,
                    backlog_threshold=dt.timedelta(seconds=900),
                ).reconcile()
            assert sorted(numbers) == list(range(1, sum(counts) + 1))
            assert sorted(m.audit_log_id for m in members) == sorted(ids)
            assert report.consistent, report.findings

    asyncio.run(scenario())


def test_postgres_uuid_order_matches_the_canonical_python_order() -> None:
    async def scenario() -> None:
        async with _scratch_schema() as engine:
            ids = [uuid4() for _ in range(64)]
            await _seed(engine, [BASE] * len(ids), ids)  # one shared timestamp: id decides

            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session, session.begin():
                repo = AuditBatchRepository(session)
                selected = await repo.list_unbatched_events(hash_version=HASH_SCHEME_V3, limit=64)
                batch = await AuditBatchService(
                    batches=repo, max_size=64, backlog_threshold=dt.timedelta(seconds=900)
                ).seal_next_batch()
                assert batch is not None
                members = (
                    await session.execute(
                        select(AuditBatchMember).order_by(AuditBatchMember.leaf_index)
                    )
                ).scalars()

            assert [e.id for e in selected] == sorted(ids)
            assert [m.audit_log_id for m in members] == sorted(ids)
            assert batch.first_occurred_at.tzinfo is not None

    asyncio.run(scenario())


# -- real driver-error classification (ADR-027 decision 10) ------------------------------------
#
# Each case seals batch 1 (two events) for real, then hands ``add_sealed_batch`` crafted rows
# that PostgreSQL must refuse. The assertions prove the metadata came from the real driver:
# the SQLAlchemy asyncpg adapter's error, chained to a genuine ``asyncpg.exceptions`` class —
# test doubles (tests/test_audit_batches.py) can satisfy neither check. No case depends on
# the order in which PostgreSQL checks unique indexes.


@dataclass(frozen=True)
class _Sealed:
    batch: AuditBatch
    member_event: UUID
    fresh: tuple[UUID, UUID]


def _crafted(**changes: object) -> AuditBatch:
    fields: dict[str, object] = {
        "id": uuid4(),
        "batch_number": 2,
        "protocol_version": 1,
        "hash_version": 3,
        "leaf_count": 1,
        "root": "a" * 64,
        "commitment": "e" * 64,
        "first_occurred_at": BASE,
        "last_occurred_at": BASE,
        **changes,
    }
    return AuditBatch(**fields)


def _member(batch: AuditBatch, audit_log_id: UUID, index: int = 0) -> AuditBatchMember:
    return AuditBatchMember(
        batch_id=batch.id, audit_log_id=audit_log_id, leaf_index=index, digest="b" * 64
    )


Build = Callable[[_Sealed], tuple[AuditBatch, list[AuditBatchMember]]]


def _twin(sealed: _Sealed) -> tuple[AuditBatch, list[AuditBatchMember]]:
    """An exact copy of batch 1 — what a losing sealer builds: same number, same root, same
    commitment. Both ``batch_number`` and ``commitment`` collide; either may be reported."""
    original = sealed.batch
    twin = _crafted(
        batch_number=original.batch_number,
        leaf_count=original.leaf_count,
        root=original.root,
        commitment=original.commitment,
    )
    return twin, [_member(twin, sealed.member_event)]


def _commitment_without_number(sealed: _Sealed) -> tuple[AuditBatch, list[AuditBatchMember]]:
    batch = _crafted(batch_number=2, commitment=sealed.batch.commitment)
    return batch, [_member(batch, sealed.fresh[0])]


def _duplicate_position(sealed: _Sealed) -> tuple[AuditBatch, list[AuditBatchMember]]:
    batch = _crafted(leaf_count=2)
    return batch, [_member(batch, sealed.fresh[0], 0), _member(batch, sealed.fresh[1], 0)]


def _with_fresh(**changes: object) -> Build:
    def build(sealed: _Sealed) -> tuple[AuditBatch, list[AuditBatchMember]]:
        batch = _crafted(**changes)
        return batch, [_member(batch, sealed.fresh[0])]

    return build


def _with_already_batched_event(sealed: _Sealed) -> tuple[AuditBatch, list[AuditBatchMember]]:
    batch = _crafted(batch_number=2)
    return batch, [_member(batch, sealed.member_event)]


def _with_missing_event(sealed: _Sealed) -> tuple[AuditBatch, list[AuditBatchMember]]:
    batch = _crafted(batch_number=2)
    return batch, [_member(batch, uuid4())]


#: (build, expected error, asyncpg class, SQLSTATE, expected classification). For the twin the
#: reported constraint is order-dependent, so its expectation is a set of acceptable names.
CASES: list[tuple[str, Build, type[Exception], str, str, str, set[str | None]]] = [
    (
        "B1-batch-number-race",
        _with_fresh(batch_number=1),
        BatchSealConflictError,
        "UniqueViolationError",
        "23505",
        "unique",
        {"uq_audit_batches_batch_number"},
    ),
    (
        "B2-membership-race",
        _with_already_batched_event,
        BatchSealConflictError,
        "UniqueViolationError",
        "23505",
        "unique",
        {"uq_audit_batch_members_audit_log_id"},
    ),
    (
        "B3-identical-twin-number-present",
        _twin,
        BatchSealConflictError,
        "UniqueViolationError",
        "23505",
        "unique",
        {"uq_audit_batches_batch_number", "uq_audit_batches_commitment"},
    ),
    (
        "B4-commitment-number-absent",
        _commitment_without_number,
        BatchSealIntegrityError,
        "UniqueViolationError",
        "23505",
        "unique",
        {"uq_audit_batches_commitment"},
    ),
    (
        "B5-duplicate-leaf-position",
        _duplicate_position,
        BatchSealIntegrityError,
        "UniqueViolationError",
        "23505",
        "unique",
        {"uq_audit_batch_members_batch_id_leaf_index"},
    ),
    (
        "C1-check-leaf-count",
        _with_fresh(leaf_count=0),
        BatchSealIntegrityError,
        "CheckViolationError",
        "23514",
        "check",
        {"ck_audit_batches_leaf_count_positive"},
    ),
    (
        "C1-check-hash-version",
        _with_fresh(hash_version=2),
        BatchSealIntegrityError,
        "CheckViolationError",
        "23514",
        "check",
        {"ck_audit_batches_hash_version_v3"},
    ),
    (
        "C2-foreign-key",
        _with_missing_event,
        BatchSealIntegrityError,
        "ForeignKeyViolationError",
        "23503",
        "foreign_key",
        {"fk_audit_batch_members_audit_logs_audit_log_id"},
    ),
    (
        "C3-not-null",
        _with_fresh(root=None),
        BatchSealIntegrityError,
        "NotNullViolationError",
        "23502",
        "not_null",
        {None},
    ),
]


async def _row_counts(session: AsyncSession) -> tuple[int, int]:
    batches = await session.execute(select(func.count()).select_from(AuditBatch))
    members = await session.execute(select(func.count()).select_from(AuditBatchMember))
    return int(batches.scalar_one()), int(members.scalar_one())


async def _seal_first_batch(engine: AsyncEngine) -> _Sealed:
    """Four events; batch 1 takes the first two, leaving two unbatched."""
    ids = [uuid4() for _ in range(4)]
    await _seed(engine, [BASE + dt.timedelta(seconds=i) for i in range(4)], ids)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        batch = await AuditBatchService(
            batches=AuditBatchRepository(session),
            max_size=2,
            backlog_threshold=dt.timedelta(seconds=900),
        ).seal_next_batch()
    assert batch is not None and batch.batch_number == 1
    return _Sealed(batch=batch, member_event=ids[0], fresh=(ids[2], ids[3]))


@pytest.mark.parametrize(
    ("build", "expected", "driver_class", "sqlstate", "kind", "constraints"),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_real_postgres_integrity_errors_are_classified(
    build: Build,
    expected: type[Exception],
    driver_class: str,
    sqlstate: str,
    kind: str,
    constraints: set[str | None],
) -> None:
    async def scenario() -> None:
        async with _scratch_schema() as engine:
            sealed = await _seal_first_batch(engine)
            factory = async_sessionmaker(engine, expire_on_commit=False)

            async with factory() as session, session.begin():
                before = await _row_counts(session)
                assert before == (1, 2)
                batch, members = build(sealed)

                with pytest.raises(expected) as raised:
                    await AuditBatchRepository(session).add_sealed_batch(batch, members)

                # Atomic: the savepoint removed every row of the refused batch, and the
                # transaction is still usable for this read.
                assert await _row_counts(session) == before

            cause = raised.value.__cause__
            assert isinstance(cause, IntegrityError)
            adapted, driver = cause.orig, getattr(cause.orig, "__cause__", None)
            # Real driver metadata, not a test double.
            assert type(adapted).__module__ == "sqlalchemy.dialects.postgresql.asyncpg"
            assert type(driver).__module__ == "asyncpg.exceptions"
            assert type(driver).__name__ == driver_class
            assert getattr(driver, "sqlstate", None) == sqlstate
            assert getattr(adapted, "sqlstate", None) == sqlstate

            violation = classify_integrity_error(cause)
            assert violation.kind == kind
            assert violation.constraint in constraints
            assert violation.constraint == getattr(driver, "constraint_name", None)
            if expected is BatchSealIntegrityError:
                assert not isinstance(raised.value, BatchSealConflictError)
                assert isinstance(raised.value, BatchSealIntegrityError)
                assert (raised.value.violation, raised.value.constraint) == (
                    violation.kind,
                    violation.constraint,
                )
            print(f"reported: {violation}")  # recorded for the order-dependent twin case

            async with factory() as fresh:
                assert await _row_counts(fresh) == before

    asyncio.run(scenario())


def test_classification_types_are_the_repository_s_own() -> None:
    """Guards the import above against drifting to a test double of the same name."""
    assert IntegrityViolation.__module__ == "app.modules.consent.repository"
