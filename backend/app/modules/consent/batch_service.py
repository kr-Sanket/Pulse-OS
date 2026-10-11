"""Merkle batch sealing and database-only reconciliation (ADR-027, M6.3).

**Sealing** turns the oldest unbatched v3 audit events into one immutable batch: admission and
ordering by ``V3Batch``, the next contiguous ``batch_number``, the commitment ``C``, and batch
plus membership written together in one savepoint. It is invoked asynchronously — never from a
healthcare request — and owns no transaction: the caller commits on success and rolls back on
any exception. Scheduling it is deferred (ADR-027); M6.3 provides the operation only.

**Reconciliation** recomputes, from the database alone, everything a sealed batch asserts and
reports each disagreement as a finding. It writes nothing: verdicts are computed on demand,
never stored (ADR-027 decision 9). Its honest limit is the database itself — someone able to
rewrite an event, its membership digest, the batch root and the commitment consistently is
caught only once commitments are compared with the chain (a later stage).

Findings and errors carry batch numbers and event ids only — never digests or event content.
"""

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from app.modules.consent.anchoring import InvalidDigestError
from app.modules.consent.merkle import (
    MERKLE_PROTOCOL_VERSION,
    InvalidCommitmentInputError,
    MerkleError,
    MerkleTree,
    V3Batch,
    batch_commitment,
)
from app.modules.consent.models import AuditBatch, AuditBatchMember, AuditLog
from app.modules.consent.repository import AuditBatchRepository
from app.modules.consent.service import (
    HASH_SCHEME_V3,
    UnsupportedHashSchemeError,
    as_utc,
    recompute_event_hash,
)
from app.shared.time import utc_now


class FindingKind(StrEnum):
    """What reconciliation can report. A backlog or late arrival is a signal to look at, not
    proof of tampering on its own; every other kind means stored evidence disagrees."""

    #: A v3 event older than the backlog threshold is in no batch.
    BACKLOG = "BACKLOG"
    #: An event sorts before the end of an earlier batch — possibly backdated, possibly a slow
    #: transaction that committed after a later event was sealed.
    LATE_ARRIVAL = "LATE_ARRIVAL"
    #: ``batch_number`` is not contiguous from 1; the finding names a missing number.
    BATCH_NUMBER_GAP = "BATCH_NUMBER_GAP"
    #: A batch's own fields are impossible: unknown protocol, not v3, a covered range that does
    #: not match its members, or a field the commitment encoding cannot accept.
    BATCH_METADATA_INVALID = "BATCH_METADATA_INVALID"
    #: The number of membership rows differs from ``leaf_count``.
    MEMBER_COUNT_MISMATCH = "MEMBER_COUNT_MISMATCH"
    #: Leaf indices are not exactly ``0 .. n-1``.
    LEAF_INDEX_INVALID = "LEAF_INDEX_INVALID"
    #: A membership row's audit event no longer exists.
    MEMBER_EVENT_MISSING = "MEMBER_EVENT_MISSING"
    #: A member's audit event no longer claims ``hash_version`` 3.
    MEMBER_NOT_V3 = "MEMBER_NOT_V3"
    #: A member's event does not recompute to the sealed digest, or its stored digest differs.
    MEMBER_DIGEST_MISMATCH = "MEMBER_DIGEST_MISMATCH"
    #: The root rebuilt from the sealed digests, in ``leaf_index`` order, differs.
    ROOT_MISMATCH = "ROOT_MISMATCH"
    #: The commitment recomputed from the stored fields differs from the stored one.
    COMMITMENT_MISMATCH = "COMMITMENT_MISMATCH"
    #: An unbatched event of a supported version does not recompute to its stored digest under
    #: its own label — an edited row, or one relabelled (e.g. v3 → v2) without a matching
    #: digest. A relabel *with* a consistent digest rewrite is indistinguishable from a genuine
    #: event of that version and is not reported (ADR-023, ADR-027 decision 13).
    EVENT_DIGEST_MISMATCH = "EVENT_DIGEST_MISMATCH"
    #: An unbatched event carries a ``hash_version`` no scheme defines. It is never
    #: reinterpreted under another version.
    UNSUPPORTED_HASH_VERSION = "UNSUPPORTED_HASH_VERSION"


@dataclass(frozen=True, slots=True)
class Finding:
    """One disagreement. Identifies *where* — a batch number and/or an event id — never
    what the digest or event content was."""

    kind: FindingKind
    batch_number: int | None = None
    audit_log_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    findings: tuple[Finding, ...]
    batches_checked: int
    members_checked: int
    unbatched_v3_events: int
    #: Unbatched events of every version recomputed under their own labels.
    unbatched_events_checked: int

    @property
    def consistent(self) -> bool:
        """No finding of any kind. Says nothing about events deleted before sealing, and
        nothing about the chain — see the module docstring."""
        return not self.findings

    def of_kind(self, kind: FindingKind) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if finding.kind is kind)


#: The canonical position key, timezone-normalised (SQLite returns naive, Postgres aware).
def _canonical_key(event: AuditLog) -> tuple[datetime, UUID]:
    return (as_utc(event.occurred_at), event.id)


class AuditBatchService:
    """Seals Merkle batches of v3 audit events and reconciles them against the database."""

    def __init__(
        self,
        *,
        batches: AuditBatchRepository,
        max_size: int,
        backlog_threshold: timedelta,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if type(max_size) is not int or max_size < 1:
            raise ValueError("max_size must be a positive integer")
        if backlog_threshold < timedelta(0):
            raise ValueError("backlog_threshold must not be negative")
        self._batches = batches
        self._max_size = max_size
        self._backlog_threshold = backlog_threshold
        self._now = clock

    # -- sealing -------------------------------------------------------------------------

    async def seal_next_batch(self) -> AuditBatch | None:
        """Seal the oldest unbatched v3 events, up to ``max_size``, as the next batch.

        Returns ``None`` — and writes nothing — when no event is eligible: an empty batch is
        never created. Otherwise the batch and every membership row are inserted in one
        savepoint, so a failure leaves no partial membership.

        Raises, with nothing written:

        * ``IneligibleEventError`` — a selected row is not a verified v3 event (for instance
          one altered after it was written). Sealing fails closed and stays blocked on that
          row until it is investigated: batching around it would hide it;
        * ``BatchSealConflictError`` — another sealer committed first; roll back and retry;
        * ``BatchSealIntegrityError`` — the database refused the batch for a reason that is not
          a sealing race (CHECK, foreign key, NOT NULL, another UNIQUE, or unclassifiable).
          Not retryable: retrying would fail the same way.
        """
        await self._batches.lock_for_sealing()
        events = await self._batches.list_unbatched_events(
            hash_version=HASH_SCHEME_V3, limit=self._max_size
        )
        if not events:
            return None

        sealed = V3Batch(events)  # admission and canonical order; refuses the whole batch
        by_id = {event.id: event for event in events}
        first = by_id[sealed.leaves[0].audit_log_id]
        last = by_id[sealed.leaves[-1].audit_log_id]
        batch_number = await self._batches.next_batch_number()
        leaf_count = len(sealed.leaves)

        batch = AuditBatch(
            id=uuid4(),
            batch_number=batch_number,
            protocol_version=MERKLE_PROTOCOL_VERSION,
            hash_version=HASH_SCHEME_V3,
            leaf_count=leaf_count,
            root=sealed.root,
            commitment=batch_commitment(
                protocol_version=MERKLE_PROTOCOL_VERSION,
                batch_number=batch_number,
                leaf_count=leaf_count,
                root=sealed.root,
            ),
            first_occurred_at=as_utc(first.occurred_at),
            last_occurred_at=as_utc(last.occurred_at),
        )
        members = [
            AuditBatchMember(
                id=uuid4(),
                batch_id=batch.id,
                audit_log_id=leaf.audit_log_id,
                leaf_index=position,
                digest=leaf.digest,
            )
            for position, leaf in enumerate(sealed.leaves)
        ]
        return await self._batches.add_sealed_batch(batch, members)

    # -- reconciliation ------------------------------------------------------------------

    async def reconcile(self) -> ReconciliationReport:
        """Check every sealed batch, every unbatched event and the v3 backlog against the
        database (ADR-027 §13)."""
        batches = await self._batches.list_batches()
        rows = await self._batches.list_members_with_events()
        every_unbatched = await self._batches.all_unbatched_events()
        unbatched = [event for event in every_unbatched if event.hash_version == HASH_SCHEME_V3]

        members_by_batch: dict[UUID, list[tuple[AuditBatchMember, AuditLog | None]]] = defaultdict(
            list
        )
        for member, event in rows:
            members_by_batch[member.batch_id].append((member, event))

        findings: list[Finding] = []
        findings.extend(_number_gaps(batches))
        for batch in batches:
            findings.extend(_check_batch(batch, members_by_batch.get(batch.id, [])))
        findings.extend(_unbatched_integrity(every_unbatched))
        findings.extend(_late_arrivals(batches, members_by_batch, unbatched))
        findings.extend(self._backlog(unbatched))

        return ReconciliationReport(
            findings=tuple(findings),
            batches_checked=len(batches),
            members_checked=len(rows),
            unbatched_v3_events=len(unbatched),
            unbatched_events_checked=len(every_unbatched),
        )

    def _backlog(self, unbatched: Sequence[AuditLog]) -> list[Finding]:
        cutoff = self._now() - self._backlog_threshold
        return [
            Finding(FindingKind.BACKLOG, audit_log_id=event.id)
            for event in unbatched
            if as_utc(event.occurred_at) <= cutoff
        ]


def _unbatched_integrity(events: Sequence[AuditLog]) -> list[Finding]:
    """Recompute every unbatched event under its **own** stored version (ADR-027 §13).

    Batched events are not re-checked here: ``_check_batch`` compares them with their sealed
    membership digests, which is the stronger check. Events arrive in canonical order, so the
    findings are deterministic.

    What this can and cannot see: a relabel or an edit that leaves the stored digest stale is
    reported; a relabel *with* a digest consistently rewritten under the new version is,
    on database evidence alone, indistinguishable from a genuine event of that version and
    passes — the same pre-sealing window as deletion (ADR-023, ADR-027 decision 13). A
    consistent v1/v2 event is not a finding: it is historical, simply not batch-eligible.
    """
    findings: list[Finding] = []
    for event in events:
        try:
            recomputed = recompute_event_hash(event)
        except UnsupportedHashSchemeError:
            findings.append(Finding(FindingKind.UNSUPPORTED_HASH_VERSION, audit_log_id=event.id))
            continue
        if recomputed != event.event_hash:
            findings.append(Finding(FindingKind.EVENT_DIGEST_MISMATCH, audit_log_id=event.id))
    return findings


def _number_gaps(batches: Sequence[AuditBatch]) -> list[Finding]:
    """Every number missing from ``1 .. highest``. Only the database side: a batch deleted
    together with every later one leaves no gap here, which is what the chain-side orphan
    check (a later stage) exists for."""
    present = {batch.batch_number for batch in batches}
    highest = max(present, default=0)
    return [
        Finding(FindingKind.BATCH_NUMBER_GAP, batch_number=number)
        for number in range(1, highest + 1)
        if number not in present
    ]


def _check_batch(
    batch: AuditBatch, members: Sequence[tuple[AuditBatchMember, AuditLog | None]]
) -> list[Finding]:
    number = batch.batch_number
    findings: list[Finding] = []

    def report(kind: FindingKind, audit_log_id: UUID | None = None) -> None:
        findings.append(Finding(kind, batch_number=number, audit_log_id=audit_log_id))

    if batch.protocol_version != MERKLE_PROTOCOL_VERSION or batch.hash_version != HASH_SCHEME_V3:
        report(FindingKind.BATCH_METADATA_INVALID)

    if len(members) != batch.leaf_count:
        report(FindingKind.MEMBER_COUNT_MISMATCH)
    if sorted(member.leaf_index for member, _ in members) != list(range(len(members))):
        report(FindingKind.LEAF_INDEX_INVALID)

    events: list[AuditLog] = []
    for member, event in members:
        if event is None:
            report(FindingKind.MEMBER_EVENT_MISSING, member.audit_log_id)
            continue
        events.append(event)
        if event.hash_version != HASH_SCHEME_V3:
            report(FindingKind.MEMBER_NOT_V3, member.audit_log_id)
            continue
        if event.event_hash != member.digest or recompute_event_hash(event) != member.digest:
            report(FindingKind.MEMBER_DIGEST_MISMATCH, member.audit_log_id)

    if events:
        keys = [_canonical_key(event) for event in events]
        if (
            as_utc(batch.first_occurred_at) != min(keys)[0]
            or as_utc(batch.last_occurred_at) != max(keys)[0]
        ):
            report(FindingKind.BATCH_METADATA_INVALID)

    # The root is rebuilt from the digests *as sealed*, in the persisted order — never
    # re-sorted — so it checks the membership rows themselves; the per-member comparison
    # above is what ties those digests back to the events.
    ordered = [member.digest for member, _ in sorted(members, key=lambda pair: pair[0].leaf_index)]
    try:
        rebuilt = MerkleTree(ordered).root
    except (MerkleError, InvalidDigestError):
        rebuilt = None
    if rebuilt != batch.root:
        report(FindingKind.ROOT_MISMATCH)

    try:
        expected = batch_commitment(
            protocol_version=batch.protocol_version,
            batch_number=batch.batch_number,
            leaf_count=batch.leaf_count,
            root=batch.root,
        )
    except (InvalidCommitmentInputError, InvalidDigestError):
        report(FindingKind.BATCH_METADATA_INVALID)
    else:
        if expected != batch.commitment:
            report(FindingKind.COMMITMENT_MISMATCH)
    return findings


def _late_arrivals(
    batches: Sequence[AuditBatch],
    members_by_batch: dict[UUID, list[tuple[AuditBatchMember, AuditLog | None]]],
    unbatched: Sequence[AuditLog],
) -> list[Finding]:
    """Events that sort before the end of an earlier batch (ADR-027 decision 13).

    Compared on the full canonical key ``(occurred_at, id)``, not the timestamp alone, so a
    batch boundary that falls between two events sharing a timestamp is not a false alarm.
    A batched event is late if it sorts before the highest key of any *earlier* batch; an
    unbatched event, if it sorts before the highest key of any sealed batch.
    """
    findings: list[Finding] = []
    highest_so_far: tuple[datetime, UUID] | None = None
    for batch in batches:
        events = [event for _, event in members_by_batch.get(batch.id, []) if event is not None]
        if highest_so_far is not None:
            findings.extend(
                Finding(
                    FindingKind.LATE_ARRIVAL, batch_number=batch.batch_number, audit_log_id=e.id
                )
                for e in events
                if _canonical_key(e) < highest_so_far
            )
        if events:
            batch_high = max(_canonical_key(event) for event in events)
            highest_so_far = (
                batch_high if highest_so_far is None else max(highest_so_far, batch_high)
            )
    if highest_so_far is not None:
        findings.extend(
            Finding(FindingKind.LATE_ARRIVAL, audit_log_id=event.id)
            for event in unbatched
            if _canonical_key(event) < highest_so_far
        )
    return findings
