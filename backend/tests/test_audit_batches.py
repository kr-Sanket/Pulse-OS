"""Merkle batch sealing, commitments and database-only reconciliation (ADR-027, M6.3).

Runs on the SQLite harness. Real concurrency between database connections cannot be
exercised there (one in-memory connection, writers serialised), so the concurrent-sealer
cases interleave two sealers deterministically on one session — the losing sealer computes
its batch from a state the winner has already changed, which is exactly the race the UNIQUE
constraints settle. PostgreSQL-specific behaviour lives in ``test_audit_batches_postgres.py``.
"""

import asyncio
import contextlib
import datetime as dt
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from app.core.config import Settings
from app.modules.auth.domain import Role
from app.modules.auth.models import User
from app.modules.consent.anchoring import InvalidDigestError
from app.modules.consent.batch_service import (
    AuditBatchService,
    Finding,
    FindingKind,
    ReconciliationReport,
)
from app.modules.consent.dependencies import build_audit_batch_service
from app.modules.consent.errors import BatchSealConflictError, BatchSealIntegrityError
from app.modules.consent.merkle import (
    COMMITMENT_PREFIX,
    MERKLE_PROTOCOL_VERSION,
    IneligibleEventError,
    InvalidCommitmentInputError,
    V3Batch,
    _keccak256,
    batch_commitment,
    verify_proof,
)
from app.modules.consent.models import (
    AuditAction,
    AuditAnchorEntry,
    AuditBatch,
    AuditBatchMember,
    AuditLog,
)
from app.modules.consent.repository import (
    SEALING_RACE_CONSTRAINTS,
    AuditBatchRepository,
    IntegrityViolation,
    classify_integrity_error,
)
from app.modules.consent.service import (
    HASH_SCHEME_V1,
    HASH_SCHEME_V2,
    HASH_SCHEME_V3,
    recompute_event_hash,
)
from app.modules.patients.models import Patient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import sqlite_session

NOW = dt.datetime(2026, 10, 11, 12, 0, tzinfo=dt.UTC)
BASE = NOW - dt.timedelta(hours=1)
BACKLOG = dt.timedelta(seconds=900)

#: ``merkle.py``'s pinned five-leaf and one-leaf roots (tests/test_audit_merkle.py).
ROOT_5 = "9649d2b300d317f168dd1ac9b6c8db26888dc5cb4d28bd394e22fa75d0cb1952"
ROOT_1 = "5f61df1468962c8107c77ae5f01bbd92c363c87a057eba326bd87ca93188e313"

#: ADR-027 decision 5's pinned commitment vectors. Computed with pycryptodome and checked by
#: hand against OpenSSL's ``keccak-256`` when the ADR was written (manual, not in CI).
COMMITMENT_VECTORS = [
    (1, 1, 5, ROOT_5, "7d2d9dd7205f9adb892bd361857652127df7e954f3132228e7724aeb53476c36"),
    (1, 2, 1, ROOT_1, "dcf485fefd095822e3191e95048dfe944a8dcdc7e0412397a9fb1c53af8caa4c"),
]


# -- harness ------------------------------------------------------------------------------


@dataclass
class World:
    session: AsyncSession
    repo: AuditBatchRepository
    user_id: UUID
    patient_id: UUID


async def _world(session: AsyncSession) -> World:
    user = User(firebase_uid=f"fb-{uuid4()}", role=Role.PATIENT)
    session.add(user)
    await session.flush()
    patient = Patient(user_id=user.id, health_id="PHI-IND-2026-1QE8DVR", full_name="Patient One")
    session.add(patient)
    await session.flush()
    return World(session, AuditBatchRepository(session), user.id, patient.id)


async def _event(
    world: World,
    *,
    seconds: float,
    scheme: int = HASH_SCHEME_V3,
    event_id: UUID | None = None,
    at: dt.datetime | None = None,
) -> AuditLog:
    event = AuditLog(
        id=event_id or uuid4(),
        actor_user_id=world.user_id,
        actor_role=Role.PATIENT,
        action=AuditAction.RECORD_VIEWED,
        patient_id=world.patient_id,
        request_context=None,
        occurred_at=at or BASE + dt.timedelta(seconds=seconds),
        actor_hospital_id=None,
        hash_version=scheme,
        event_hash="",
    )
    event.event_hash = recompute_event_hash(event)
    world.session.add(event)
    await world.session.flush()
    return event


def _service(world: World, *, max_size: int = 256, repo: Any = None) -> AuditBatchService:
    return AuditBatchService(
        batches=repo or world.repo, max_size=max_size, backlog_threshold=BACKLOG, clock=lambda: NOW
    )


async def _count(session: AsyncSession, model: type[Any]) -> int:
    return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def _refused(session: AsyncSession, row: object) -> None:
    """Insert ``row`` in a savepoint and expect the schema to refuse it.

    Added *inside* the savepoint so its rollback also discards the row; added outside, the
    rejected object would stay pending and be retried by the next flush.
    """
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(row)
            await session.flush()


async def _members(session: AsyncSession, batch: AuditBatch) -> list[AuditBatchMember]:
    result = await session.execute(
        select(AuditBatchMember)
        .where(AuditBatchMember.batch_id == batch.id)
        .order_by(AuditBatchMember.leaf_index)
    )
    return list(result.scalars())


def _kinds(report: ReconciliationReport) -> set[FindingKind]:
    return {finding.kind for finding in report.findings}


def run(scenario: Any) -> None:
    async def wrapped() -> None:
        async with sqlite_session() as session:
            await scenario(await _world(session))

    asyncio.run(wrapped())


# -- commitment ---------------------------------------------------------------------------


@pytest.mark.parametrize(("version", "number", "count", "root", "expected"), COMMITMENT_VECTORS)
def test_commitment_matches_pinned_vectors(
    version: int, number: int, count: int, root: str, expected: str
) -> None:
    assert (
        batch_commitment(protocol_version=version, batch_number=number, leaf_count=count, root=root)
        == expected
    )


def test_commitment_preimage_is_46_packed_big_endian_bytes() -> None:
    preimage = (
        COMMITMENT_PREFIX
        + bytes([1])
        + (1).to_bytes(8, "big")
        + (5).to_bytes(4, "big")
        + bytes.fromhex(ROOT_5)
    )

    assert len(preimage) == 46
    assert preimage.hex().startswith("0201" + "0000000000000001" + "00000005")
    assert _keccak256(preimage).hex() == COMMITMENT_VECTORS[0][4]


@pytest.mark.parametrize(
    "changes",
    [
        {"protocol_version": 2},
        {"batch_number": 2},
        {"leaf_count": 6},
        {"root": ROOT_1},
    ],
)
def test_every_commitment_field_is_bound(changes: dict[str, Any]) -> None:
    fields: dict[str, Any] = {
        "protocol_version": 1,
        "batch_number": 1,
        "leaf_count": 5,
        "root": ROOT_5,
    }
    assert batch_commitment(**{**fields, **changes}) != COMMITMENT_VECTORS[0][4]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("protocol_version", 0),
        ("protocol_version", 256),
        ("protocol_version", True),
        ("batch_number", 0),
        ("batch_number", -1),
        ("batch_number", 2**64),
        ("batch_number", "1"),
        ("leaf_count", 0),
        ("leaf_count", 2**32),
        ("leaf_count", 5.0),
    ],
)
def test_commitment_refuses_out_of_range_or_non_integer_fields(field: str, value: Any) -> None:
    fields: dict[str, Any] = {
        "protocol_version": 1,
        "batch_number": 1,
        "leaf_count": 5,
        "root": ROOT_5,
        field: value,
    }
    with pytest.raises(InvalidCommitmentInputError):
        batch_commitment(**fields)


def test_commitment_accepts_the_field_maxima() -> None:
    commitment = batch_commitment(
        protocol_version=255, batch_number=2**64 - 1, leaf_count=2**32 - 1, root=ROOT_5
    )
    assert len(commitment) == 64


@pytest.mark.parametrize("root", ["", "A" * 64, "0x" + "a" * 64])
def test_commitment_refuses_a_malformed_root(root: str) -> None:
    with pytest.raises(InvalidDigestError):
        batch_commitment(protocol_version=1, batch_number=1, leaf_count=1, root=root)


# -- sealing ------------------------------------------------------------------------------


def test_nothing_eligible_seals_nothing() -> None:
    async def scenario(world: World) -> None:
        assert await _service(world).seal_next_batch() is None
        assert await _count(world.session, AuditBatch) == 0

    run(scenario)


def test_historical_v1_v2_events_are_never_batched_or_rewritten() -> None:
    async def scenario(world: World) -> None:
        v1 = await _event(world, seconds=1, scheme=HASH_SCHEME_V1)
        v2 = await _event(world, seconds=2, scheme=HASH_SCHEME_V2)
        before = {e.id: (e.hash_version, e.event_hash) for e in (v1, v2)}

        assert await _service(world).seal_next_batch() is None
        v3 = await _event(world, seconds=3)
        batch = await _service(world).seal_next_batch()

        assert batch is not None
        assert [m.audit_log_id for m in await _members(world.session, batch)] == [v3.id]
        world.session.expire_all()
        for event_id, original in before.items():
            refreshed = await world.session.get(AuditLog, event_id)
            assert refreshed is not None
            assert (refreshed.hash_version, refreshed.event_hash) == original

    run(scenario)


def test_a_sealed_batch_persists_authoritative_metadata() -> None:
    async def scenario(world: World) -> None:
        # Written out of order: sealing must order canonically, not by insertion.
        events = [await _event(world, seconds=s) for s in (30, 10, 20)]
        ordered = sorted(events, key=lambda e: e.occurred_at)

        batch = await _service(world).seal_next_batch()

        assert batch is not None
        members = await _members(world.session, batch)
        expected = V3Batch(events)
        assert batch.batch_number == 1
        assert batch.protocol_version == MERKLE_PROTOCOL_VERSION
        assert batch.hash_version == HASH_SCHEME_V3
        assert batch.leaf_count == 3
        assert batch.root == expected.root
        assert batch.commitment == batch_commitment(
            protocol_version=1, batch_number=1, leaf_count=3, root=expected.root
        )
        assert [m.audit_log_id for m in members] == [e.id for e in ordered]
        assert [m.leaf_index for m in members] == [0, 1, 2]
        assert [m.digest for m in members] == [e.event_hash for e in ordered]
        assert batch.first_occurred_at == ordered[0].occurred_at
        assert batch.last_occurred_at == ordered[-1].occurred_at
        # Every member proves membership against the persisted, trusted metadata.
        for member in members:
            proof = expected.proof_for(member.audit_log_id)
            assert verify_proof(
                member.digest,
                proof,
                batch.root,
                trusted_leaf_index=member.leaf_index,
                trusted_leaf_count=batch.leaf_count,
            )

    run(scenario)


def test_the_maximum_size_splits_into_contiguous_batches_then_stops() -> None:
    async def scenario(world: World) -> None:
        events = [await _event(world, seconds=s) for s in range(5)]
        service = _service(world, max_size=2)

        sealed = [await service.seal_next_batch() for _ in range(3)]
        again = await service.seal_next_batch()

        assert [b.batch_number for b in sealed if b] == [1, 2, 3]
        assert [b.leaf_count for b in sealed if b] == [2, 2, 1]
        assert again is None
        assert await _count(world.session, AuditBatchMember) == len(events)
        assert await _count(world.session, AuditBatch) == 3

    run(scenario)


def test_sealing_is_idempotent_once_everything_is_batched() -> None:
    async def scenario(world: World) -> None:
        await _event(world, seconds=1)
        service = _service(world)
        first = await service.seal_next_batch()

        assert first is not None
        assert await service.seal_next_batch() is None
        assert await service.seal_next_batch() is None
        assert await _count(world.session, AuditBatch) == 1

    run(scenario)


def test_a_tampered_unsealed_v3_event_fails_closed_and_writes_nothing() -> None:
    async def scenario(world: World) -> None:
        await _event(world, seconds=1)
        bad = await _event(world, seconds=2)
        bad.request_context = "edited after writing"
        await world.session.flush()

        with pytest.raises(IneligibleEventError) as raised:
            await _service(world).seal_next_batch()

        assert str(bad.id) in str(raised.value)
        assert await _count(world.session, AuditBatch) == 0
        assert await _count(world.session, AuditBatchMember) == 0

    run(scenario)


def test_sealing_does_not_touch_per_event_anchors() -> None:
    async def scenario(world: World) -> None:
        await _event(world, seconds=1)
        await _service(world).seal_next_batch()

        assert await _count(world.session, AuditAnchorEntry) == 0

    run(scenario)


def test_a_service_needs_a_positive_integer_maximum() -> None:
    async def scenario(world: World) -> None:
        for bad in (0, -1, True):
            with pytest.raises(ValueError):
                _service(world, max_size=bad)

    run(scenario)


# -- concurrency and atomicity --------------------------------------------------------------


class _RacingRepository(AuditBatchRepository):
    """Lets a competing sealer win between this sealer's reads and its insert.

    ``next_batch_number`` first computes the number from the state it saw, then runs the
    competitor to completion, then returns the stale number — the interleaving of two
    sealers that both read before either wrote.
    """

    def __init__(self, session: AsyncSession, competitor: AuditBatchService, stale: bool) -> None:
        super().__init__(session)
        self._competitor = competitor
        self._stale = stale

    async def next_batch_number(self) -> int:
        seen = await super().next_batch_number()
        await self._competitor.seal_next_batch()
        return seen if self._stale else await super().next_batch_number()


@pytest.mark.parametrize(
    "stale", [True, False], ids=["same-batch-number", "same-events-new-number"]
)
def test_a_losing_concurrent_sealer_writes_nothing(stale: bool) -> None:
    """Both constraints, separately: a stale number collides on UNIQUE ``batch_number``; a
    fresh number with already-batched events collides on UNIQUE ``audit_log_id``. Either
    way the savepoint removes every row of the losing batch, the batch row included."""

    async def scenario(world: World) -> None:
        events = [await _event(world, seconds=s) for s in range(3)]
        competitor = _service(world)
        loser = _service(world, repo=_RacingRepository(world.session, competitor, stale))

        with pytest.raises(BatchSealConflictError):
            await loser.seal_next_batch()

        batches = (await world.session.execute(select(AuditBatch))).scalars().all()
        assert [b.batch_number for b in batches] == [1]
        members = await _members(world.session, batches[0])
        assert sorted(m.audit_log_id for m in members) == sorted(e.id for e in events)
        assert await _count(world.session, AuditBatchMember) == 3
        # The session is still usable: the next run seals nothing new, without error.
        assert await competitor.seal_next_batch() is None

    run(scenario)


def test_a_failed_insert_leaves_no_partial_membership() -> None:
    """A member that collides half-way through rolls back the batch and every member."""

    async def scenario(world: World) -> None:
        first = await _event(world, seconds=1)
        await _service(world).seal_next_batch()
        fresh = await _event(world, seconds=2)
        batch = AuditBatch(
            id=uuid4(),
            batch_number=2,
            protocol_version=1,
            hash_version=3,
            leaf_count=2,
            root=ROOT_5,
            commitment=batch_commitment(
                protocol_version=1, batch_number=2, leaf_count=2, root=ROOT_5
            ),
            first_occurred_at=first.occurred_at,
            last_occurred_at=fresh.occurred_at,
        )
        members = [
            AuditBatchMember(
                batch_id=batch.id, audit_log_id=fresh.id, leaf_index=0, digest="a" * 64
            ),
            # Already in batch 1: violates UNIQUE audit_log_id.
            AuditBatchMember(
                batch_id=batch.id, audit_log_id=first.id, leaf_index=1, digest="b" * 64
            ),
        ]

        with pytest.raises(BatchSealConflictError):
            await world.repo.add_sealed_batch(batch, members)

        assert await _count(world.session, AuditBatch) == 1
        assert await _count(world.session, AuditBatchMember) == 1

    run(scenario)


# -- database constraints (model metadata; migration parity is in test_alembic) ---------------


def _raw_batch(**changes: Any) -> AuditBatch:
    fields: dict[str, Any] = {
        "id": uuid4(),
        "batch_number": 1,
        "protocol_version": 1,
        "hash_version": 3,
        "leaf_count": 1,
        "root": ROOT_1,
        "commitment": "c" * 64,
        "first_occurred_at": BASE,
        "last_occurred_at": BASE,
        **changes,
    }
    return AuditBatch(**fields)


@pytest.mark.parametrize(
    "changes",
    [{"leaf_count": 0}, {"batch_number": 0}, {"hash_version": 2}],
    ids=["empty-batch", "batch-number-zero", "not-v3"],
)
def test_the_schema_refuses_impossible_batches(changes: dict[str, Any]) -> None:
    async def scenario(world: World) -> None:
        await _refused(world.session, _raw_batch(**changes))

    run(scenario)


def test_the_schema_refuses_a_duplicate_batch_number_and_negative_index() -> None:
    async def scenario(world: World) -> None:
        event = await _event(world, seconds=1)
        world.session.add(_raw_batch(batch_number=1))
        await world.session.flush()

        await _refused(world.session, _raw_batch(batch_number=1, commitment="d" * 64))

        batch = _raw_batch(batch_number=2, commitment="e" * 64)
        world.session.add(batch)
        await world.session.flush()
        await _refused(
            world.session,
            AuditBatchMember(
                batch_id=batch.id, audit_log_id=event.id, leaf_index=-1, digest="a" * 64
            ),
        )
        assert await _count(world.session, AuditBatch) == 2

    run(scenario)


# -- reconciliation ---------------------------------------------------------------------------


async def _sealed_world(world: World) -> tuple[list[AuditLog], list[AuditBatch]]:
    """Two batches of two v3 events each, sealed and consistent."""
    events = [await _event(world, seconds=s) for s in (10, 20, 30, 40)]
    service = _service(world, max_size=2)
    batches = [await service.seal_next_batch(), await service.seal_next_batch()]
    assert all(batches)
    return events, [b for b in batches if b]


def test_a_consistent_database_reconciles_clean_and_reconciliation_writes_nothing() -> None:
    async def scenario(world: World) -> None:
        await _sealed_world(world)
        before = (
            await _count(world.session, AuditBatch),
            await _count(world.session, AuditBatchMember),
        )

        report = await _service(world).reconcile()

        assert report.consistent, report.findings
        assert (report.batches_checked, report.members_checked) == (2, 4)
        assert report.unbatched_v3_events == 0
        assert not world.session.dirty and not world.session.new
        after = (
            await _count(world.session, AuditBatch),
            await _count(world.session, AuditBatchMember),
        )
        assert before == after

    run(scenario)


def test_an_altered_event_is_a_member_digest_mismatch() -> None:
    async def scenario(world: World) -> None:
        events, _ = await _sealed_world(world)
        events[1].request_context = "edited"
        await world.session.flush()

        report = await _service(world).reconcile()

        assert report.of_kind(FindingKind.MEMBER_DIGEST_MISMATCH) == (
            Finding(FindingKind.MEMBER_DIGEST_MISMATCH, batch_number=1, audit_log_id=events[1].id),
        )

    run(scenario)


def test_an_altered_event_with_a_recomputed_hash_is_still_caught() -> None:
    """Editing the row *and* its event_hash consistently still diverges from the sealed digest."""

    async def scenario(world: World) -> None:
        events, _ = await _sealed_world(world)
        events[2].request_context = "edited"
        events[2].event_hash = recompute_event_hash(events[2])
        await world.session.flush()

        report = await _service(world).reconcile()

        assert {f.audit_log_id for f in report.of_kind(FindingKind.MEMBER_DIGEST_MISMATCH)} == {
            events[2].id
        }

    run(scenario)


def test_a_relabelled_event_is_member_not_v3() -> None:
    async def scenario(world: World) -> None:
        events, _ = await _sealed_world(world)
        events[0].hash_version = HASH_SCHEME_V2
        await world.session.flush()

        assert FindingKind.MEMBER_NOT_V3 in _kinds(await _service(world).reconcile())

    run(scenario)


def test_an_altered_membership_digest_breaks_member_and_root() -> None:
    async def scenario(world: World) -> None:
        _, batches = await _sealed_world(world)
        member = (await _members(world.session, batches[0]))[0]
        member.digest = "0" * 64
        await world.session.flush()

        kinds = _kinds(await _service(world).reconcile())

        assert {FindingKind.MEMBER_DIGEST_MISMATCH, FindingKind.ROOT_MISMATCH} <= kinds
        assert FindingKind.COMMITMENT_MISMATCH not in kinds

    run(scenario)


def test_an_altered_root_breaks_root_and_commitment() -> None:
    async def scenario(world: World) -> None:
        _, batches = await _sealed_world(world)
        batches[1].root = ROOT_5
        await world.session.flush()

        report = await _service(world).reconcile()

        assert {(f.kind, f.batch_number) for f in report.findings} == {
            (FindingKind.ROOT_MISMATCH, 2),
            (FindingKind.COMMITMENT_MISMATCH, 2),
        }

    run(scenario)


def test_an_altered_commitment_is_a_commitment_mismatch_only() -> None:
    async def scenario(world: World) -> None:
        _, batches = await _sealed_world(world)
        batches[0].commitment = "f" * 64
        await world.session.flush()

        report = await _service(world).reconcile()

        assert report.findings == (Finding(FindingKind.COMMITMENT_MISMATCH, batch_number=1),)

    run(scenario)


def test_an_altered_leaf_count_is_caught_by_count_and_commitment() -> None:
    async def scenario(world: World) -> None:
        _, batches = await _sealed_world(world)
        batches[0].leaf_count = 3
        await world.session.flush()

        kinds = _kinds(await _service(world).reconcile())

        assert {FindingKind.MEMBER_COUNT_MISMATCH, FindingKind.COMMITMENT_MISMATCH} <= kinds

    run(scenario)


def test_a_moved_leaf_index_is_caught() -> None:
    async def scenario(world: World) -> None:
        _, batches = await _sealed_world(world)
        member = (await _members(world.session, batches[0]))[0]
        member.leaf_index = 7
        await world.session.flush()

        kinds = _kinds(await _service(world).reconcile())

        assert {FindingKind.LEAF_INDEX_INVALID, FindingKind.ROOT_MISMATCH} <= kinds

    run(scenario)


def test_a_deleted_member_is_caught() -> None:
    async def scenario(world: World) -> None:
        events, batches = await _sealed_world(world)
        member = (await _members(world.session, batches[1]))[1]
        await world.session.delete(member)
        await world.session.flush()

        report = await _service(world).reconcile()

        assert {FindingKind.MEMBER_COUNT_MISMATCH, FindingKind.ROOT_MISMATCH} <= _kinds(report)
        # Its event is unbatched again, and sorts inside an already sealed range.
        assert report.unbatched_v3_events == 1
        assert Finding(FindingKind.LATE_ARRIVAL, audit_log_id=events[3].id) not in report.findings

    run(scenario)


class _MissingEventRepository(AuditBatchRepository):
    """Reports one member's audit row as gone — what an outer join returns after the event
    row was deleted with foreign keys bypassed (the harness enforces them)."""

    def __init__(self, session: AsyncSession, missing: UUID) -> None:
        super().__init__(session)
        self._missing = missing

    async def list_members_with_events(self) -> list[tuple[AuditBatchMember, AuditLog | None]]:
        rows = await super().list_members_with_events()
        return [(m, None if m.audit_log_id == self._missing else e) for m, e in rows]


def test_a_missing_event_row_is_caught() -> None:
    async def scenario(world: World) -> None:
        events, _ = await _sealed_world(world)
        repo = _MissingEventRepository(world.session, events[0].id)

        report = await _service(world, repo=repo).reconcile()

        assert (
            Finding(FindingKind.MEMBER_EVENT_MISSING, batch_number=1, audit_log_id=events[0].id)
            in report.findings
        )

    run(scenario)


def test_a_batch_number_gap_is_caught() -> None:
    async def scenario(world: World) -> None:
        _, batches = await _sealed_world(world)
        batches[1].batch_number = 3
        await world.session.flush()

        report = await _service(world).reconcile()

        assert Finding(FindingKind.BATCH_NUMBER_GAP, batch_number=2) in report.findings
        assert Finding(FindingKind.COMMITMENT_MISMATCH, batch_number=3) in report.findings

    run(scenario)


@pytest.mark.parametrize(
    "changes",
    [
        {"protocol_version": 2},
        {"first_occurred_at": BASE},
        {"last_occurred_at": NOW},
    ],
    ids=["unknown-protocol", "range-start", "range-end"],
)
def test_impossible_batch_metadata_is_caught(changes: dict[str, Any]) -> None:
    async def scenario(world: World) -> None:
        _, batches = await _sealed_world(world)
        for name, value in changes.items():
            setattr(batches[0], name, value)
        await world.session.flush()

        report = await _service(world).reconcile()

        assert Finding(FindingKind.BATCH_METADATA_INVALID, batch_number=1) in report.findings

    run(scenario)


def test_a_backdated_event_is_a_late_arrival_before_and_after_sealing() -> None:
    async def scenario(world: World) -> None:
        await _sealed_world(world)
        backdated = await _event(world, seconds=15)  # inside batch 1's range

        unsealed = await _service(world).reconcile()
        assert Finding(FindingKind.LATE_ARRIVAL, audit_log_id=backdated.id) in unsealed.findings

        batch = await _service(world).seal_next_batch()
        assert batch is not None and batch.batch_number == 3
        sealed = await _service(world).reconcile()
        assert sealed.of_kind(FindingKind.LATE_ARRIVAL) == (
            Finding(FindingKind.LATE_ARRIVAL, batch_number=3, audit_log_id=backdated.id),
        )

    run(scenario)


def test_a_batch_boundary_between_equal_timestamps_is_not_a_late_arrival() -> None:
    """The cap can split two events that share an ``occurred_at``; canonical order by id
    puts the lower id first, so the second batch's event is not 'before' the first's."""

    async def scenario(world: World) -> None:
        moment = BASE + dt.timedelta(seconds=5)
        low = await _event(world, seconds=0, at=moment, event_id=UUID(int=1))
        high = await _event(world, seconds=0, at=moment, event_id=UUID(int=2))
        service = _service(world, max_size=1)

        first, second = await service.seal_next_batch(), await service.seal_next_batch()

        assert first is not None and second is not None
        assert [m.audit_log_id for m in await _members(world.session, first)] == [low.id]
        assert [m.audit_log_id for m in await _members(world.session, second)] == [high.id]
        assert (await service.reconcile()).consistent

    run(scenario)


def test_backlog_is_reported_only_past_the_threshold() -> None:
    async def scenario(world: World) -> None:
        old = await _event(world, seconds=0, at=NOW - BACKLOG - dt.timedelta(seconds=1))
        await _event(world, seconds=0, at=NOW - BACKLOG + dt.timedelta(seconds=1))
        v2 = await _event(world, seconds=0, at=NOW - dt.timedelta(days=1), scheme=HASH_SCHEME_V2)

        report = await _service(world).reconcile()

        assert report.of_kind(FindingKind.BACKLOG) == (
            Finding(FindingKind.BACKLOG, audit_log_id=old.id),
        )
        assert v2.id not in {f.audit_log_id for f in report.findings}

    run(scenario)


def test_findings_carry_identifiers_only() -> None:
    async def scenario(world: World) -> None:
        events, _ = await _sealed_world(world)
        events[0].request_context = "edited"
        await world.session.flush()

        report = await _service(world).reconcile()
        rendered = repr(report.findings)

        assert report.findings
        for event in events:
            assert event.event_hash not in rendered
            assert str(event.patient_id) not in rendered
        assert "edited" not in rendered

    run(scenario)


# -- configuration ----------------------------------------------------------------------------


def test_settings_default_to_the_approved_values() -> None:
    fields = Settings.model_fields
    assert fields["audit_batch_max_size"].default == 256
    assert fields["audit_batch_interval_seconds"].default == 300
    assert fields["audit_batch_backlog_threshold_seconds"].default == 900


def test_the_factory_applies_configured_size_and_threshold() -> None:
    async def scenario(world: World) -> None:
        settings = Settings(
            audit_batch_max_size=2, audit_batch_backlog_threshold_seconds=60, _env_file=None
        )
        for second in range(3):
            await _event(world, seconds=second)

        batch = await build_audit_batch_service(world.session, settings).seal_next_batch()

        assert batch is not None and batch.leaf_count == 2

    run(scenario)


# -- integrity-error classification: only sealing races are retryable --------------------------


async def _one_sealed(world: World) -> AuditBatch:
    await _event(world, seconds=1)
    batch = await _service(world).seal_next_batch()
    assert batch is not None
    return batch


async def _counts(world: World) -> tuple[int, int]:
    return (await _count(world.session, AuditBatch), await _count(world.session, AuditBatchMember))


async def _refused_as_integrity(
    world: World, batch: AuditBatch, members: list[AuditBatchMember]
) -> BatchSealIntegrityError:
    """Expect a non-retryable refusal that writes nothing and leaves the session usable."""
    before = await _counts(world)
    with pytest.raises(BatchSealIntegrityError) as raised:
        await world.repo.add_sealed_batch(batch, members)
    assert not isinstance(raised.value, BatchSealConflictError)
    # Nothing written, and the savepoint left the session usable: this query runs after it.
    assert await _counts(world) == before
    return raised.value


def _member(batch: AuditBatch, audit_log_id: UUID, index: int) -> AuditBatchMember:
    return AuditBatchMember(
        batch_id=batch.id, audit_log_id=audit_log_id, leaf_index=index, digest="a" * 64
    )


def test_an_identical_batch_race_reported_on_the_commitment_stays_retryable() -> None:
    """SQLite reports an identical-batch race on the commitment, not the number; the lookup of
    the number is what keeps it retryable (the deterministic race test depends on it)."""

    async def scenario(world: World) -> None:
        sealed = await _one_sealed(world)
        member = (await _members(world.session, sealed))[0]
        twin = _raw_batch(
            batch_number=sealed.batch_number,
            leaf_count=sealed.leaf_count,
            root=sealed.root,
            commitment=sealed.commitment,
        )

        with pytest.raises(BatchSealConflictError) as raised:
            await world.repo.add_sealed_batch(twin, [_member(twin, member.audit_log_id, 0)])

        cause = raised.value.__cause__
        assert isinstance(cause, IntegrityError)
        assert classify_integrity_error(cause).constraint in {
            "uq_audit_batches_commitment",
            "uq_audit_batches_batch_number",
        }
        assert await _counts(world) == (1, 1)

    run(scenario)


def test_the_two_sealing_races_stay_retryable() -> None:
    """Real SQLite collisions on ``batch_number`` and on ``audit_log_id`` classify as races."""

    async def scenario(world: World) -> None:
        sealed = await _one_sealed(world)
        member = (await _members(world.session, sealed))[0]
        fresh = await _event(world, seconds=2)

        same_number = _raw_batch(batch_number=1, commitment="d" * 64)
        with pytest.raises(BatchSealConflictError) as by_number:
            await world.repo.add_sealed_batch(same_number, [_member(same_number, fresh.id, 0)])

        same_event = _raw_batch(batch_number=2, commitment="e" * 64)
        with pytest.raises(BatchSealConflictError) as by_event:
            await world.repo.add_sealed_batch(
                same_event, [_member(same_event, member.audit_log_id, 0)]
            )

        for raised, constraint in (
            (by_number, "uq_audit_batches_batch_number"),
            (by_event, "uq_audit_batch_members_audit_log_id"),
        ):
            cause = raised.value.__cause__
            assert isinstance(cause, IntegrityError)
            assert classify_integrity_error(cause) == IntegrityViolation("unique", constraint)
        assert await _counts(world) == (1, 1)

    run(scenario)


def test_a_check_violation_is_not_a_conflict() -> None:
    async def scenario(world: World) -> None:
        event = await _event(world, seconds=1)
        batch = _raw_batch(leaf_count=0)

        error = await _refused_as_integrity(world, batch, [_member(batch, event.id, 0)])

        assert (error.violation, error.constraint) == ("check", None)

    run(scenario)


def test_a_foreign_key_violation_is_not_a_conflict() -> None:
    async def scenario(world: World) -> None:
        batch = _raw_batch()

        error = await _refused_as_integrity(world, batch, [_member(batch, uuid4(), 0)])

        assert error.violation == "foreign_key"

    run(scenario)


def test_a_not_null_violation_is_not_a_conflict() -> None:
    async def scenario(world: World) -> None:
        batch = _raw_batch(root=None)

        error = await _refused_as_integrity(world, batch, [])

        assert error.violation == "not_null"

    run(scenario)


def test_a_commitment_only_collision_is_not_a_conflict() -> None:
    """Another number, the same commitment: tampering or a bug, never a sealing race."""

    async def scenario(world: World) -> None:
        sealed = await _one_sealed(world)
        fresh = await _event(world, seconds=2)
        batch = _raw_batch(batch_number=2, commitment=sealed.commitment)

        error = await _refused_as_integrity(world, batch, [_member(batch, fresh.id, 0)])

        assert (error.violation, error.constraint) == ("unique", "uq_audit_batches_commitment")

    run(scenario)


def test_a_duplicate_leaf_index_is_not_a_conflict() -> None:
    """A fresh batch id cannot be raced, so a repeated position is a bug, not contention."""

    async def scenario(world: World) -> None:
        first, second = await _event(world, seconds=1), await _event(world, seconds=2)
        batch = _raw_batch(leaf_count=2)

        error = await _refused_as_integrity(
            world, batch, [_member(batch, first.id, 0), _member(batch, second.id, 0)]
        )

        assert (error.violation, error.constraint) == (
            "unique",
            "uq_audit_batch_members_batch_id_leaf_index",
        )

    run(scenario)


def test_the_refusal_carries_schema_identifiers_only() -> None:
    async def scenario(world: World) -> None:
        sealed = await _one_sealed(world)
        fresh = await _event(world, seconds=2)
        batch = _raw_batch(batch_number=2, commitment=sealed.commitment)

        error = await _refused_as_integrity(world, batch, [_member(batch, fresh.id, 0)])
        message = str(error)

        assert sealed.commitment not in message
        assert str(fresh.id) not in message
        assert "INSERT" not in message.upper()

    run(scenario)


class _AdaptedPostgresError(Exception):
    """Shaped like SQLAlchemy's asyncpg adapter error: ``sqlstate`` on it, the driver error
    (with ``constraint_name``) chained as ``__cause__``."""

    def __init__(self, sqlstate: str, constraint_name: str | None) -> None:
        super().__init__("adapted")
        self.sqlstate = sqlstate
        driver = Exception("asyncpg")
        driver.constraint_name = constraint_name  # type: ignore[attr-defined]
        self.__cause__ = driver


class _SqliteShapedError(Exception):
    def __init__(self, errorname: str, message: str) -> None:
        super().__init__(message)
        self.sqlite_errorname = errorname


def _integrity(orig: BaseException) -> IntegrityError:
    return IntegrityError("statement withheld", None, orig)


@pytest.mark.parametrize(
    ("sqlstate", "constraint", "expected"),
    [
        (
            "23505",
            "uq_audit_batches_batch_number",
            IntegrityViolation("unique", "uq_audit_batches_batch_number"),
        ),
        (
            "23505",
            "uq_audit_batch_members_audit_log_id",
            IntegrityViolation("unique", "uq_audit_batch_members_audit_log_id"),
        ),
        (
            "23505",
            "uq_audit_batches_commitment",
            IntegrityViolation("unique", "uq_audit_batches_commitment"),
        ),
        (
            "23505",
            "uq_audit_batch_members_batch_id_leaf_index",
            IntegrityViolation("unique", "uq_audit_batch_members_batch_id_leaf_index"),
        ),
        ("23505", "pk_audit_batches", IntegrityViolation("unique", "pk_audit_batches")),
        ("23505", None, IntegrityViolation("unique", None)),
        (
            "23514",
            "ck_audit_batches_leaf_count_positive",
            IntegrityViolation("check", "ck_audit_batches_leaf_count_positive"),
        ),
        (
            "23503",
            "fk_audit_batch_members_audit_logs_audit_log_id",
            IntegrityViolation("foreign_key", "fk_audit_batch_members_audit_logs_audit_log_id"),
        ),
        ("23502", None, IntegrityViolation("not_null", None)),
        ("23P01", "some_exclusion", IntegrityViolation("unknown", "some_exclusion")),
    ],
)
def test_postgres_shaped_errors_classify_from_sqlstate_and_constraint_name(
    sqlstate: str, constraint: str | None, expected: IntegrityViolation
) -> None:
    violation = classify_integrity_error(_integrity(_AdaptedPostgresError(sqlstate, constraint)))

    assert violation == expected
    assert violation.is_sealing_race is (
        expected.kind == "unique" and expected.constraint in SEALING_RACE_CONSTRAINTS
    )


@pytest.mark.parametrize(
    "orig",
    [
        Exception("no driver metadata at all"),
        _SqliteShapedError("SQLITE_CONSTRAINT_UNIQUE", "UNIQUE constraint failed: other.column"),
        _SqliteShapedError(
            "SQLITE_CONSTRAINT_UNIQUE", "UNIQUE constraint failed: audit_batches.batch_number "
        ),
        _SqliteShapedError("SQLITE_CONSTRAINT_TRIGGER", "constraint failed"),
    ],
    ids=["no-metadata", "unlisted-unique", "near-miss-message", "unlisted-errorname"],
)
def test_unclassifiable_errors_fail_closed(orig: BaseException) -> None:
    violation = classify_integrity_error(_integrity(orig))

    assert violation.is_sealing_race is False
    assert violation.constraint is None


class _FirstResult:
    def __init__(self, row: tuple[UUID] | None) -> None:
        self._row = row

    def first(self) -> tuple[UUID] | None:
        return self._row


class _RaisingSession:
    """Just enough session for ``add_sealed_batch``: the flush fails with a given error, and
    the follow-up lookup reports whether a batch with the same number exists."""

    def __init__(self, error: IntegrityError, *, number_taken: bool) -> None:
        self._error = error
        self._number_taken = number_taken

    def begin_nested(self) -> contextlib.nullcontext[None]:
        return contextlib.nullcontext()

    def add(self, _: object) -> None:
        return None

    def add_all(self, _: object) -> None:
        return None

    async def flush(self) -> None:
        raise self._error

    async def execute(self, _: object) -> _FirstResult:
        return _FirstResult((uuid4(),) if self._number_taken else None)


_NUMBER_RACE = _AdaptedPostgresError("23505", "uq_audit_batches_batch_number")
_EVENT_RACE = _AdaptedPostgresError("23505", "uq_audit_batch_members_audit_log_id")
_COMMITMENT = _AdaptedPostgresError("23505", "uq_audit_batches_commitment")


@pytest.mark.parametrize(
    ("orig", "number_taken", "expected"),
    [
        (_NUMBER_RACE, False, BatchSealConflictError),
        (_EVENT_RACE, False, BatchSealConflictError),
        (_COMMITMENT, True, BatchSealConflictError),
        (_COMMITMENT, False, BatchSealIntegrityError),
        (_AdaptedPostgresError("23505", None), True, BatchSealIntegrityError),
        (
            _AdaptedPostgresError("23514", "ck_audit_batches_hash_version_v3"),
            True,
            BatchSealIntegrityError,
        ),
        (_AdaptedPostgresError("23503", None), False, BatchSealIntegrityError),
        (Exception("unclassifiable"), True, BatchSealIntegrityError),
    ],
    ids=[
        "pg-number-race",
        "pg-event-race",
        "pg-commitment-identical-batch-race",
        "pg-commitment-number-not-taken",
        "pg-unique-unnamed",
        "pg-check",
        "pg-fk",
        "unknown",
    ],
)
def test_add_sealed_batch_maps_postgres_shaped_errors(
    orig: BaseException, number_taken: bool, expected: type[Exception]
) -> None:
    error = _integrity(orig)
    session = _RaisingSession(error, number_taken=number_taken)
    repo = AuditBatchRepository(cast(AsyncSession, session))

    with pytest.raises(expected) as raised:
        asyncio.run(repo.add_sealed_batch(_raw_batch(), []))

    assert raised.value.__cause__ is error
    if expected is BatchSealIntegrityError:
        assert not isinstance(raised.value, BatchSealConflictError)


# -- unbatched event integrity (ADR-027 decision 13; ADR-023 qualified) --------------------------


def test_an_unbatched_v3_event_relabelled_to_v2_is_a_digest_mismatch() -> None:
    """The relabel escapes sealing (no longer v3) — reconciliation is what now sees it."""

    async def scenario(world: World) -> None:
        event = await _event(world, seconds=1)
        event.hash_version = HASH_SCHEME_V2  # Keccak digest left as written
        await world.session.flush()

        report = await _service(world).reconcile()

        assert report.of_kind(FindingKind.EVENT_DIGEST_MISMATCH) == (
            Finding(FindingKind.EVENT_DIGEST_MISMATCH, audit_log_id=event.id),
        )
        assert report.of_kind(FindingKind.UNSUPPORTED_HASH_VERSION) == ()
        assert (report.unbatched_v3_events, report.unbatched_events_checked) == (0, 1)
        assert await _service(world).seal_next_batch() is None  # not batch-eligible

    run(scenario)


def test_an_unbatched_v3_event_with_a_stale_digest_is_reported_and_still_blocks_sealing() -> None:
    async def scenario(world: World) -> None:
        event = await _event(world, seconds=1)
        event.request_context = "edited after writing"
        await world.session.flush()

        report = await _service(world).reconcile()

        assert report.of_kind(FindingKind.EVENT_DIGEST_MISMATCH) == (
            Finding(FindingKind.EVENT_DIGEST_MISMATCH, audit_log_id=event.id),
        )
        with pytest.raises(IneligibleEventError):  # fail-closed sealing is unchanged
            await _service(world).seal_next_batch()
        assert await _count(world.session, AuditBatch) == 0

    run(scenario)


def test_an_unsupported_hash_version_is_reported_and_never_reinterpreted() -> None:
    async def scenario(world: World) -> None:
        event = await _event(world, seconds=1)
        event.hash_version = 4
        await world.session.flush()

        report = await _service(world).reconcile()

        assert report.of_kind(FindingKind.UNSUPPORTED_HASH_VERSION) == (
            Finding(FindingKind.UNSUPPORTED_HASH_VERSION, audit_log_id=event.id),
        )
        assert report.of_kind(FindingKind.EVENT_DIGEST_MISMATCH) == ()

    run(scenario)


def test_consistent_historical_v1_and_v2_events_are_not_findings() -> None:
    async def scenario(world: World) -> None:
        await _event(world, seconds=1, scheme=HASH_SCHEME_V1)
        await _event(world, seconds=2, scheme=HASH_SCHEME_V2)

        report = await _service(world).reconcile()

        assert report.consistent, report.findings
        assert (report.unbatched_v3_events, report.unbatched_events_checked) == (0, 2)
        assert await _service(world).seal_next_batch() is None  # historical: never batched

    run(scenario)


def test_a_batched_event_relabelled_after_sealing_stays_a_batch_finding_only() -> None:
    """Batched events are checked against their sealed digests, not re-reported here."""

    async def scenario(world: World) -> None:
        events, _ = await _sealed_world(world)
        events[0].hash_version = HASH_SCHEME_V2
        await world.session.flush()

        report = await _service(world).reconcile()

        assert (
            Finding(FindingKind.MEMBER_NOT_V3, batch_number=1, audit_log_id=events[0].id)
            in report.findings
        )
        assert report.of_kind(FindingKind.EVENT_DIGEST_MISMATCH) == ()
        assert report.unbatched_events_checked == 0

    run(scenario)


def test_a_consistent_relabel_and_rewrite_before_sealing_is_not_detectable() -> None:
    """KNOWN LIMITATION, pinned so it stays visible (ADR-023 qualified, ADR-027 §13): a v3
    event relabelled to v2 *with* its digest rewritten as a valid v2 digest is, on database
    evidence alone, indistinguishable from a genuine v2 event. Reconciliation must not report
    it as a digest mismatch — it is consistent — and it escapes sealing. Only sealing before
    the change, or database-level append-only enforcement (deferred to M7), prevents this."""

    async def scenario(world: World) -> None:
        event = await _event(world, seconds=1)
        event.hash_version = HASH_SCHEME_V2
        event.event_hash = recompute_event_hash(event)  # consistent under v2
        await world.session.flush()

        report = await _service(world).reconcile()

        assert report.consistent
        assert await _service(world).seal_next_batch() is None

    run(scenario)


def test_unbatched_integrity_findings_follow_canonical_order() -> None:
    async def scenario(world: World) -> None:
        later = await _event(world, seconds=20)
        earlier = await _event(world, seconds=10)
        for event in (later, earlier):
            event.request_context = "edited"
        await world.session.flush()

        report = await _service(world).reconcile()

        assert [f.audit_log_id for f in report.of_kind(FindingKind.EVENT_DIGEST_MISMATCH)] == [
            earlier.id,
            later.id,
        ]

    run(scenario)
