"""Anchoring and integrity verification for audit events (ADR-004, ADR-026).

The lifecycle this owns, end to end:

    clinical/consent operation → audit_logs row (authoritative, append-only)
        → canonical digest (already stored as ``event_hash``)
        → AuditAnchor.submit(digest)
        → AnchorReceipt
        → audit_anchors row (digest + network + reference)

**Anchoring is deferred, never inline.** No clinical path calls into this service, and that
is the design rather than an omission (ADR-026). ``_write_audit`` runs inside the caller's
transaction, so anchoring there would put an external adapter on the critical path of every
record read and every consent decision — precisely what ADR-004 forbids ("chain downtime
never blocks or delays a consent decision"). A sweep also matches the eventual shape: a real
chain answers in seconds and charges gas, and batching many digests into one transaction is
only expressible over a backlog.

**Verification is computed, never stored.** There is no ``status`` column to go stale; a
verdict is derived on demand from three independently stored things:

1. the digest recomputed from the ``audit_logs`` row's own columns,
2. the ``event_hash`` recorded on that row,
3. the ``digest`` recorded on the anchor when it was published.

Tampering that edits a row and recomputes its hash still diverges from (3); tampering that
edits only the row diverges from (2). What the *local* adapter cannot defend against is an
attacker who rewrites all three, because everything lives in one database — that is exactly
the gap a real chain closes, and the honest limit of this milestone.
"""

import logging
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.modules.auth.domain import AuthenticatedUser
from app.modules.consent.anchoring import AnchorReceipt, AuditAnchor, InvalidDigestError
from app.modules.consent.errors import (
    AuditEventNotFoundError,
    BatchAnchoredEventError,
    DuplicateAnchorError,
    PatientProfileNotFoundError,
    UnanchorableAuditEventError,
)
from app.modules.consent.merkle import (
    MERKLE_PROTOCOL_VERSION,
    InvalidCommitmentInputError,
    StoredBatch,
    batch_commitment,
    rebuild_stored_batch,
)
from app.modules.consent.models import AuditAnchorEntry, AuditBatch, AuditBatchMember, AuditLog
from app.modules.consent.repository import (
    AuditAnchorRepository,
    AuditBatchRepository,
    AuditLogRepository,
)
from app.modules.consent.service import (
    HASH_SCHEME_V3,
    UnsupportedHashSchemeError,
    recompute_event_hash,
)
from app.modules.patients.directory import PatientDirectoryService

logger = logging.getLogger(__name__)

#: Network identifier for locally verified v3 Merkle batches. Distinguishes local Merkle
#: batch verification from external blockchain anchoring (ADR-027).
LOCAL_MERKLE_BATCH_NETWORK: Final = "local-merkle-batch"


class IntegrityStatus(StrEnum):
    """The verdict for one audit event.

    Four members rather than a boolean, because "we cannot vouch for this yet" and "this has
    been altered" are opposite messages to show a patient, and the two failure modes point
    at different culprits.
    """

    #: No anchor exists yet. Says nothing about the event's integrity — every event is here
    #: between being written and being swept, and every event written before ADR-026.
    NOT_ANCHORED = "NOT_ANCHORED"
    #: Row hashes to its stored digest, that digest is what was anchored, and the anchor's
    #: reference is the one this network produces for it.
    VERIFIED = "VERIFIED"
    #: The row no longer hashes to what was anchored — the event's own columns were altered.
    EVENT_ALTERED = "EVENT_ALTERED"
    #: The anchor row does not match what the network would have produced for its digest.
    ANCHOR_ALTERED = "ANCHOR_ALTERED"


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    """One event's verdict, plus the anchor facts a caller may see.

    Carries no digest and no canonical payload: a verdict is what an audit reader needs,
    and republishing the hashed material would hand out a re-identification oracle for a
    trail the reader can otherwise only see rows of.
    """

    audit_log_id: UUID
    status: IntegrityStatus
    anchor: AuditAnchorEntry | None
    network: str | None = None
    reference: str | None = None
    anchored_at: datetime | None = None

    @property
    def is_anchored(self) -> bool:
        return self.anchor is not None or self.reference is not None


@dataclass(frozen=True, slots=True)
class AnchorOutcome:
    """The result of anchoring one event: the anchor, and whether this call created it."""

    anchor: AuditAnchorEntry
    created: bool


@dataclass(frozen=True, slots=True)
class SweepResult:
    """What one sweep did. ``failed`` counts events the adapter refused or errored on;
    they stay unanchored and are retried by the next sweep, in the same order.
    ``remaining`` counts only events this workflow serves — v3 events are batch-anchored."""

    anchored: int
    failed: int
    remaining: int


class AuditAnchorService:
    """Anchors audit digests and answers integrity questions about them.

    Owns no transaction, like every other service here: repositories flush, the request or
    the script commits. Verification performs no writes at all.
    """

    def __init__(
        self,
        *,
        audit: AuditLogRepository,
        anchors: AuditAnchorRepository,
        anchor_provider: AuditAnchor,
        patients: PatientDirectoryService,
        batches: AuditBatchRepository | None = None,
    ) -> None:
        self._audit = audit
        self._anchors = anchors
        self._provider = anchor_provider
        self._patients = patients
        self._batches = batches

    # -- anchoring ---------------------------------------------------------------------

    async def anchor_event(self, entry: AuditLog) -> AnchorOutcome:
        """Anchor one audit event's digest, idempotently.

        **Only ``entry.event_hash`` crosses the port** — the digest and nothing else. No
        actor, no patient, no action, no target, no timestamp from the event (ADR-004:
        hashes only, never identifiers or PHI). ``require_digest`` in the port refuses
        anything that is not a bare hex digest, so a clinical payload cannot reach an
        adapter even by mistake.

        Idempotent two ways. An event already anchored returns its existing anchor without
        calling the adapter, and a concurrent caller that wins the race is resolved by the
        UNIQUE on ``audit_log_id``: the loser reads the winner's row back rather than
        failing. ``created`` distinguishes the two for a caller that cares.

        **v3 events are refused** (``BatchAnchoredEventError``): they are anchored only in
        Merkle batches (ADR-027 decision 7). This workflow keeps serving v1/v2 rows, and
        existing per-event anchors of any version stay readable.

        **Inconsistent events are refused** (``UnanchorableAuditEventError``) before a new
        anchor is created: the version must be supported and the stored digest must recompute
        under it. Otherwise the port would publish a digest the row itself no longer backs. An
        existing anchor is still returned as-is — verification, not this path, judges it.
        """
        if entry.hash_version == HASH_SCHEME_V3:
            raise BatchAnchoredEventError()
        existing = await self._anchors.get_by_audit_log_id(entry.id)
        if existing is not None:
            return AnchorOutcome(anchor=existing, created=False)
        _require_consistent(entry)

        receipt = await self._provider.submit(entry.event_hash)
        try:
            anchor = await self._anchors.add(
                AuditAnchorEntry(
                    audit_log_id=entry.id,
                    # The digest **as published**, kept beside the event's own copy so a
                    # later divergence between them is detectable (see the model).
                    digest=entry.event_hash,
                    hash_version=entry.hash_version,
                    network=receipt.network,
                    reference=receipt.reference,
                    anchored_at=receipt.anchored_at,
                )
            )
        except DuplicateAnchorError:
            # Lost the race. The other writer's anchor is as good as this one — same digest,
            # same deterministic reference — so read it back instead of surfacing a conflict.
            winner = await self._anchors.get_by_audit_log_id(entry.id)
            if winner is None:  # pragma: no cover — UNIQUE fired, so the row exists
                raise
            return AnchorOutcome(anchor=winner, created=False)
        return AnchorOutcome(anchor=anchor, created=True)

    async def anchor_pending(self, *, limit: int) -> SweepResult:
        """Anchor the oldest unanchored events, up to ``limit``.

        The reconciliation job of ADR-004, and the only writer in normal operation. One
        adapter failure does not abandon the sweep: the event stays unanchored, is counted,
        and the next run picks it up again in the same position. Nothing here touches the
        audit rows themselves, so a sweep can never damage the trail it is attesting to.
        """
        # v3 events never enter this queue: they are batch-anchored (ADR-027 decision 7).
        pending = await self._anchors.list_unanchored_events(
            limit=limit, exclude_hash_version=HASH_SCHEME_V3
        )
        anchored = 0
        failed = 0
        for entry in pending:
            try:
                await self.anchor_event(entry)
            except (InvalidDigestError, UnanchorableAuditEventError, OSError) as exc:
                # Only ids are logged, never event content (docs/SECURITY.md).
                logger.warning(
                    "audit anchor failed", extra={"audit_log_id": str(entry.id), "error": str(exc)}
                )
                failed += 1
                continue
            anchored += 1
        return SweepResult(
            anchored=anchored,
            failed=failed,
            remaining=await self._anchors.count_unanchored(exclude_hash_version=HASH_SCHEME_V3),
        )

    # -- verification ------------------------------------------------------------------

    async def verify_for_caller(
        self, caller: AuthenticatedUser, audit_log_id: UUID
    ) -> IntegrityReport:
        """Verify one event of the caller's own trail.

        **Scope comes from the token**, exactly as ``ConsentService.list_audit_events`` takes
        it: the patient row is resolved from ``caller.user_id`` and becomes part of the
        lookup, so an event belonging to somebody else is indistinguishable from one that
        does not exist. This adds no visibility a patient did not already have over their
        own audit log.
        """
        patient = await self._patients.get_by_user_id(caller.user_id)
        if patient is None:
            raise PatientProfileNotFoundError()
        entry = await self._audit.get_for_patient(audit_log_id, patient_id=patient.id)
        if entry is None:
            raise AuditEventNotFoundError()
        return await self.verify(entry)

    async def verify(self, entry: AuditLog) -> IntegrityReport:
        """The integrity verdict for one audit event.

        **Batch evidence takes precedence, and a per-event anchor can never make a v3 event
        VERIFIED.** An event with a membership row is judged only by its batch (whatever its
        ``hash_version`` now says — that label is outside the hashed payload, so a batched
        event relabelled v2 must not escape to the weaker per-event check). Without
        membership, a per-event anchor is still assessed (``_assess_unbatched``) so that a
        contradiction is reported — but for a v3 event agreement proves nothing: the
        application never writes such a row (``BatchAnchoredEventError``) and the local
        anchor's reference is forgeable, so the best a v3 event can get from it is
        ``NOT_ANCHORED`` until it is sealed. v1/v2 events keep per-event verification.
        """
        if self._batches is not None:
            member = await self._batches.get_member_by_audit_log_id(entry.id)
            if member is not None:
                batch = await self._batches.get_batch_by_id(member.batch_id)
                if batch is None:
                    return _orphaned_member(entry)
                siblings = await self._batches.list_members_for_batch(batch.id)
                return self._assess_batched(entry, member, batch, _rebuild(batch, siblings))
        anchor = await self._anchors.get_by_audit_log_id(entry.id)
        return await self._assess_unbatched(entry, anchor)

    async def verify_many(self, entries: Sequence[AuditLog]) -> Mapping[UUID, IntegrityReport]:
        """Verdicts for a page of events, in a fixed number of *queries*, under exactly the
        precedence ``verify`` applies (batch evidence first; a per-event anchor never makes
        a v3 event VERIFIED).

        Three queries for the whole page: anchors, the full membership of every batch the
        page's events sit in, and those batches. **Each distinct batch is rebuilt once per
        page** (``rebuild_stored_batch``) and every entry of it is then checked against that
        rebuild, so CPU cost is one tree per batch rather than one per event. Nothing is
        cached across requests.
        """
        page_ids = {entry.id for entry in entries}
        anchors = await self._anchors.by_audit_log_ids(list(page_ids))

        members: dict[UUID, AuditBatchMember] = {}
        siblings_by_batch: dict[UUID, list[AuditBatchMember]] = {}
        batches: Mapping[UUID, AuditBatch] = {}
        if self._batches is not None:
            for row in await self._batches.members_sharing_batch_with(page_ids):
                siblings_by_batch.setdefault(row.batch_id, []).append(row)
                if row.audit_log_id in page_ids:
                    members[row.audit_log_id] = row
            if siblings_by_batch:
                batches = await self._batches.get_batches_by_ids(siblings_by_batch.keys())
        rebuilt = {
            batch_id: _rebuild(batch, siblings_by_batch.get(batch_id, []))
            for batch_id, batch in batches.items()
        }

        reports: dict[UUID, IntegrityReport] = {}
        for entry in entries:
            member = members.get(entry.id)
            anchor = anchors.get(entry.id)
            if member is not None:
                batch = batches.get(member.batch_id)
                reports[entry.id] = (
                    _orphaned_member(entry)
                    if batch is None
                    else self._assess_batched(entry, member, batch, rebuilt[batch.id])
                )
            else:
                reports[entry.id] = await self._assess_unbatched(entry, anchor)
        return reports

    async def _assess_unbatched(
        self, entry: AuditLog, anchor: AuditAnchorEntry | None
    ) -> IntegrityReport:
        """The verdict for an event with no batch membership.

        v1/v2: the per-event anchor decides, as it always has. v3: the anchor can only count
        *against* the event — a contradiction (``EVENT_ALTERED``/``ANCHOR_ALTERED``) is
        reported, because an anchor that disagrees with the row is evidence of a change —
        but a matching anchor is not evidence for it, so the verdict is ``NOT_ANCHORED``.
        """
        if anchor is None:
            return IntegrityReport(
                audit_log_id=entry.id, status=IntegrityStatus.NOT_ANCHORED, anchor=None
            )
        report = await self._assess(entry, anchor)
        if entry.hash_version == HASH_SCHEME_V3 and report.status is IntegrityStatus.VERIFIED:
            return IntegrityReport(
                audit_log_id=entry.id, status=IntegrityStatus.NOT_ANCHORED, anchor=None
            )
        return report

    def _assess_batched(
        self,
        entry: AuditLog,
        member: AuditBatchMember,
        batch: AuditBatch,
        stored: StoredBatch,
    ) -> IntegrityReport:
        """The comparisons for a v3 Merkle-batched audit event (ADR-027).

        VERIFIED requires every link of the chain, the same rule the proof endpoint applies
        (``verify_stored_inclusion``): the event recomputes to its stored digest, that digest
        is the member's, the batch commitment matches the stored root, **and the member is
        provably a leaf under that root** — ``stored`` is the batch rebuilt from its stored
        members (once per batch per request) and the member must be the leaf at its index of
        a tree whose root is the sealed one. A member digest edited to match an edited event
        therefore no longer passes: it changes the rebuilt root.

        Distinguishes local Merkle batch verification from external blockchain anchoring:
        network is set to 'local-merkle-batch' and anchored_at represents the local batch
        creation/sealing timestamp.
        """
        try:
            recomputed: str | None = recompute_event_hash(entry)
        except UnsupportedHashSchemeError:
            recomputed = None

        if (
            recomputed is None
            or recomputed != entry.event_hash
            or entry.event_hash != member.digest
            or entry.hash_version != HASH_SCHEME_V3
        ):
            return IntegrityReport(
                audit_log_id=entry.id,
                status=IntegrityStatus.EVENT_ALTERED,
                anchor=None,
                network=LOCAL_MERKLE_BATCH_NETWORK,
                reference=f"0x{batch.commitment}",
                anchored_at=batch.created_at,
            )

        try:
            expected_commitment = batch_commitment(
                protocol_version=batch.protocol_version,
                batch_number=batch.batch_number,
                leaf_count=batch.leaf_count,
                root=batch.root,
            )
        except (InvalidCommitmentInputError, InvalidDigestError):
            expected_commitment = None

        if (
            member.leaf_index < 0
            or member.leaf_index >= batch.leaf_count
            or batch.protocol_version != MERKLE_PROTOCOL_VERSION
            or batch.hash_version != HASH_SCHEME_V3
            or expected_commitment != batch.commitment
            or not stored.includes(leaf_index=member.leaf_index, digest=member.digest)
        ):
            return IntegrityReport(
                audit_log_id=entry.id,
                status=IntegrityStatus.ANCHOR_ALTERED,
                anchor=None,
                network=LOCAL_MERKLE_BATCH_NETWORK,
                reference=f"0x{batch.commitment}",
                anchored_at=batch.created_at,
            )

        return IntegrityReport(
            audit_log_id=entry.id,
            status=IntegrityStatus.VERIFIED,
            anchor=None,
            network=LOCAL_MERKLE_BATCH_NETWORK,
            reference=f"0x{batch.commitment}",
            anchored_at=batch.created_at,
        )

    async def _assess(self, entry: AuditLog, anchor: AuditAnchorEntry | None) -> IntegrityReport:
        """The three comparisons, in the order that makes a verdict meaningful.

        Order matters: an altered event is reported as ``EVENT_ALTERED`` even if the anchor
        row is also wrong, because the event is the thing a reader is being told about and
        the more alarming fact should not be masked by a bookkeeping one.
        """
        if anchor is None:
            return IntegrityReport(
                audit_log_id=entry.id, status=IntegrityStatus.NOT_ANCHORED, anchor=None
            )

        try:
            # Under the row's own scheme — the same resolution the writer used — so v1/v2
            # SHA-256 rows and v3 Keccak-256 rows each verify under their own rule.
            recomputed: str | None = recompute_event_hash(entry)
        except UnsupportedHashSchemeError:
            # A version this code never wrote cannot be vouched for, and ``hash_version`` sits
            # outside the hashed payload (ADR-023), so an unknown value is itself a sign the
            # row changed. Reported, never raised: one bad row must not fail a whole page.
            recomputed = None
        if recomputed != entry.event_hash or entry.event_hash != anchor.digest:
            # Either the row no longer hashes to its own digest, or its digest is no longer
            # the one that was published. Both mean the event changed after anchoring.
            return IntegrityReport(
                audit_log_id=entry.id,
                status=IntegrityStatus.EVENT_ALTERED,
                anchor=anchor,
                network=anchor.network,
                reference=anchor.reference,
                anchored_at=anchor.anchored_at,
            )

        receipt = AnchorReceipt(
            network=anchor.network, reference=anchor.reference, anchored_at=anchor.anchored_at
        )
        if not await self._provider.verify(anchor.digest, receipt):
            return IntegrityReport(
                audit_log_id=entry.id,
                status=IntegrityStatus.ANCHOR_ALTERED,
                anchor=anchor,
                network=anchor.network,
                reference=anchor.reference,
                anchored_at=anchor.anchored_at,
            )
        return IntegrityReport(
            audit_log_id=entry.id,
            status=IntegrityStatus.VERIFIED,
            anchor=anchor,
            network=anchor.network,
            reference=anchor.reference,
            anchored_at=anchor.anchored_at,
        )


def _require_consistent(entry: AuditLog) -> None:
    """Refuse an event whose stored digest is not what its own version recomputes to.

    The same version-aware ``recompute_event_hash`` the writer and the verifier use — no
    second implementation of the payload or the algorithm.
    """
    try:
        recomputed = recompute_event_hash(entry)
    except UnsupportedHashSchemeError:
        raise UnanchorableAuditEventError(reason="unsupported_hash_version") from None
    if recomputed != entry.event_hash:
        raise UnanchorableAuditEventError(reason="digest_mismatch")


def anchored_event_ids(reports: Collection[IntegrityReport]) -> set[UUID]:
    """The subset that carries an anchor — a convenience for callers summarising a page."""
    return {report.audit_log_id for report in reports if report.is_anchored}


def _rebuild(batch: AuditBatch, siblings: Sequence[AuditBatchMember]) -> StoredBatch:
    """One batch's stored membership rebuilt into its tree, from rows read in this request."""
    return rebuild_stored_batch(
        [(sibling.leaf_index, sibling.digest) for sibling in siblings],
        root=batch.root,
        leaf_count=batch.leaf_count,
    )


def _orphaned_member(entry: AuditLog) -> IntegrityReport:
    """An event whose membership row points at a batch that no longer exists.

    Not NOT_ANCHORED: the event *was* sealed, and the record of that sealing has been
    damaged. Reported as the anchor side being altered, with no anchor facts to show.
    """
    return IntegrityReport(
        audit_log_id=entry.id,
        status=IntegrityStatus.ANCHOR_ALTERED,
        anchor=None,
        network=LOCAL_MERKLE_BATCH_NETWORK,
    )
