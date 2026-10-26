"""Submit sealed batch commitments to a public chain, and verify them there (ADR-035).

Three kinds of evidence stay distinct (ADR-027 decision 7):

- **Local Merkle verification** — ``AuditBatchService.verify_batch``: members recompute,
  the root rebuilds, the stored commitment ``C`` recomputes. Database-only.
- **Submission record** — an ``audit_batch_anchors`` row: a transaction was sent and, once
  CONFIRMED, its receipt carried ``CommitmentAnchored(C)`` from the configured registry with
  enough confirmations. Operational state, written by the operator CLI.
- **On-chain verification** — ``status``: computed on demand, never stored (decision 9). The
  expected ``C`` is recomputed from the locally verified batch and looked up in the
  registry's contract state; for a confirmed submission the receipt is re-read and must
  carry that same ``C``. A transaction hash alone is never treated as proof.

Submission is retry-safe (decision 11): before sending, the registry is asked whether ``C``
is already recorded, and if so the existing on-chain record is adopted rather than sent
again. A tampered batch is never submitted. Nothing here runs on a clinical request path; no
API endpoint triggers submission.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.modules.consent.batch_service import AuditBatchService, BatchVerificationResult
from app.modules.consent.chain import (
    ChainConfigError,
    ChainError,
    CommitmentRegistry,
)
from app.modules.consent.errors import AuditBatchNotFoundError
from app.modules.consent.merkle import batch_commitment
from app.modules.consent.models import AuditBatch, AuditBatchAnchor, ChainAnchorStatus
from app.modules.consent.repository import AuditBatchAnchorRepository, AuditBatchRepository
from app.shared.time import utc_now


class LocalBatchInvalidError(Exception):
    """The batch fails local verification; its commitment must not be published."""


class SubmissionAction(StrEnum):
    """What one ``submit``/``refresh`` call did."""

    #: A transaction was broadcast; the row is PENDING.
    SUBMITTED = "SUBMITTED"
    #: The commitment was already recorded on-chain; that record was adopted, nothing sent.
    ADOPTED_EXISTING = "ADOPTED_EXISTING"
    #: The row was already CONFIRMED; nothing to do.
    ALREADY_CONFIRMED = "ALREADY_CONFIRMED"
    #: Mined with too few confirmations yet, or not mined yet.
    STILL_PENDING = "STILL_PENDING"
    #: Moved PENDING → CONFIRMED.
    CONFIRMED = "CONFIRMED"
    #: Submission or confirmation failed; ``failure_reason`` on the row says why.
    FAILED = "FAILED"
    #: No submission exists for this batch on this network.
    NOT_SUBMITTED = "NOT_SUBMITTED"


@dataclass(frozen=True, slots=True)
class SubmissionOutcome:
    batch_number: int
    action: SubmissionAction
    anchor: AuditBatchAnchor | None


class ChainVerificationStatus(StrEnum):
    """Result of reading the registry for a batch's expected commitment, on demand."""

    #: No registry is configured on this deployment.
    NOT_CONFIGURED = "NOT_CONFIGURED"
    #: The RPC endpoint could not be reached or answered malformed data.
    UNAVAILABLE = "UNAVAILABLE"
    #: The batch fails local verification, so no expected commitment can be trusted.
    LOCAL_INTEGRITY_FAILED = "LOCAL_INTEGRITY_FAILED"
    #: The expected commitment is not recorded on-chain (and no confirmation claims it is).
    NOT_ON_CHAIN = "NOT_ON_CHAIN"
    #: The expected commitment is recorded on-chain, consistent with the stored submission.
    VERIFIED = "VERIFIED"
    #: Stored submission evidence and the chain disagree (missing record, different block,
    #: or a receipt that does not carry the expected commitment).
    MISMATCH = "MISMATCH"


@dataclass(frozen=True, slots=True)
class ChainVerification:
    status: ChainVerificationStatus
    expected_commitment: str | None
    on_chain_block_number: int | None
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class BatchAnchorView:
    batch: AuditBatch
    local: BatchVerificationResult
    network: str | None
    chain_id: int | None
    contract_address: str | None
    anchor: AuditBatchAnchor | None
    chain: ChainVerification


def _expected_commitment(local: BatchVerificationResult) -> str | None:
    """``C`` recomputed from the locally verified batch fields, or None if it can't be."""
    if not local.is_valid:
        return None
    return batch_commitment(
        protocol_version=local.protocol_version,
        batch_number=local.batch_number,
        leaf_count=local.leaf_count,
        root=local.root,
    )


class BatchAnchorService:
    def __init__(
        self,
        *,
        batches: AuditBatchRepository,
        anchors: AuditBatchAnchorRepository,
        batch_service: AuditBatchService,
        registry: CommitmentRegistry | None,
        min_confirmations: int = 2,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if type(min_confirmations) is not int or min_confirmations < 1:
            raise ValueError("min_confirmations must be a positive integer")
        self._batches = batches
        self._anchors = anchors
        self._batch_service = batch_service
        self._registry = registry
        self._min_confirmations = min_confirmations
        self._now = clock

    def _require_registry(self) -> CommitmentRegistry:
        if self._registry is None:
            raise ChainConfigError("registry_not_configured")
        return self._registry

    async def _load(self, batch_number: int) -> tuple[AuditBatch, BatchVerificationResult]:
        batch = await self._batches.get_batch_by_number(batch_number)
        local = await self._batch_service.verify_batch(batch_number)
        if batch is None or local is None:
            raise AuditBatchNotFoundError()
        return batch, local

    # -- submission (operator CLI only) ---------------------------------------------------

    async def submit(self, batch_number: int) -> SubmissionOutcome:
        """Publish batch ``batch_number``'s commitment, retry-safely.

        Raises ``AuditBatchNotFoundError``, ``LocalBatchInvalidError`` (nothing is written)
        or ``ChainConfigError`` (wrong chain, no signer — nothing is written). Chain failures
        during the attempt are recorded on the row as FAILED and returned, not raised.
        """
        registry = self._require_registry()
        batch, local = await self._load(batch_number)
        expected = _expected_commitment(local)
        if expected is None or expected != batch.commitment:
            raise LocalBatchInvalidError(f"batch {batch_number} fails local verification")
        if await registry.remote_chain_id() != registry.chain_id:
            raise ChainConfigError("chain_id_mismatch")

        row = await self._anchors.get(batch_id=batch.id, network=registry.network)
        if row is not None and row.status is ChainAnchorStatus.CONFIRMED:
            return SubmissionOutcome(batch_number, SubmissionAction.ALREADY_CONFIRMED, row)
        if row is not None and row.status is ChainAnchorStatus.PENDING:
            # Never broadcast a second transaction while one is outstanding.
            return await self.refresh(batch_number)
        if row is None:
            row = AuditBatchAnchor(
                batch_id=batch.id,
                network=registry.network,
                chain_id=registry.chain_id,
                contract_address=registry.contract_address,
                commitment=expected,
                status=ChainAnchorStatus.FAILED,
            )
        else:
            # A retry of a FAILED submission: re-point it at the configured registry.
            row.chain_id = registry.chain_id
            row.contract_address = registry.contract_address
            row.commitment = expected

        try:
            recorded_block = await registry.anchored_block(expected)
            if recorded_block > 0:
                tx_hash = await registry.find_anchor_tx(expected, recorded_block)
                if tx_hash is None:
                    return await self._fail(batch_number, row, "anchor_tx_not_found")
                row.tx_hash = tx_hash
                row.block_number = recorded_block
                row.block_timestamp = await registry.block_timestamp(recorded_block)
                row.status = ChainAnchorStatus.CONFIRMED
                row.failure_reason = None
                row.confirmed_at = self._now()
                await self._anchors.save(row)
                return SubmissionOutcome(batch_number, SubmissionAction.ADOPTED_EXISTING, row)

            tx_hash = await registry.submit(expected)
        except ChainConfigError:
            raise
        except ChainError as error:
            return await self._fail(batch_number, row, error.code)

        row.tx_hash = tx_hash
        row.status = ChainAnchorStatus.PENDING
        row.failure_reason = None
        row.block_number = None
        row.block_timestamp = None
        row.submitted_at = self._now()
        await self._anchors.save(row)
        return SubmissionOutcome(batch_number, SubmissionAction.SUBMITTED, row)

    async def refresh(self, batch_number: int) -> SubmissionOutcome:
        """Advance a PENDING submission to CONFIRMED or FAILED from its mined receipt."""
        registry = self._require_registry()
        batch, _ = await self._load(batch_number)
        row = await self._anchors.get(batch_id=batch.id, network=registry.network)
        if row is None:
            return SubmissionOutcome(batch_number, SubmissionAction.NOT_SUBMITTED, None)
        if row.status is ChainAnchorStatus.CONFIRMED:
            return SubmissionOutcome(batch_number, SubmissionAction.ALREADY_CONFIRMED, row)
        if row.status is ChainAnchorStatus.FAILED or row.tx_hash is None:
            return SubmissionOutcome(batch_number, SubmissionAction.FAILED, row)

        try:
            receipt = await registry.get_receipt(row.tx_hash)
            if receipt is None:
                return SubmissionOutcome(batch_number, SubmissionAction.STILL_PENDING, row)
            if not receipt.succeeded:
                return await self._fail(batch_number, row, "transaction_reverted")
            if not receipt.records_commitment(
                contract_address=row.contract_address, commitment=row.commitment
            ):
                return await self._fail(batch_number, row, "commitment_event_missing")
            head = await registry.head_block()
            if head - receipt.block_number + 1 < self._min_confirmations:
                return SubmissionOutcome(batch_number, SubmissionAction.STILL_PENDING, row)
            # Independent read of contract state, not just the receipt.
            if await registry.anchored_block(row.commitment) != receipt.block_number:
                return await self._fail(batch_number, row, "registry_state_mismatch")
            row.block_timestamp = await registry.block_timestamp(receipt.block_number)
        except ChainError:
            # Transient: leave PENDING, the next refresh asks again.
            return SubmissionOutcome(batch_number, SubmissionAction.STILL_PENDING, row)

        row.block_number = receipt.block_number
        row.status = ChainAnchorStatus.CONFIRMED
        row.failure_reason = None
        row.confirmed_at = self._now()
        await self._anchors.save(row)
        return SubmissionOutcome(batch_number, SubmissionAction.CONFIRMED, row)

    async def _fail(
        self, batch_number: int, row: AuditBatchAnchor, reason: str
    ) -> SubmissionOutcome:
        row.status = ChainAnchorStatus.FAILED
        row.failure_reason = reason[:64]
        await self._anchors.save(row)
        return SubmissionOutcome(batch_number, SubmissionAction.FAILED, row)

    # -- verification (read-only; API and CLI) --------------------------------------------

    async def status(self, batch_number: int) -> BatchAnchorView:
        """Local verification, stored submission and a fresh on-chain check, side by side.

        Read-only: writes nothing, never submits. Raises ``AuditBatchNotFoundError``.
        """
        batch, local = await self._load(batch_number)
        registry = self._registry
        expected = _expected_commitment(local)
        if registry is None:
            anchors = await self._anchors.list_for_batch(batch.id)
            return BatchAnchorView(
                batch=batch,
                local=local,
                network=None,
                chain_id=None,
                contract_address=None,
                anchor=anchors[0] if anchors else None,
                chain=ChainVerification(
                    ChainVerificationStatus.NOT_CONFIGURED, expected, None, self._now()
                ),
            )

        row = await self._anchors.get(batch_id=batch.id, network=registry.network)
        chain = await self._verify_on_chain(registry, expected, row)
        return BatchAnchorView(
            batch=batch,
            local=local,
            network=registry.network,
            chain_id=registry.chain_id,
            contract_address=registry.contract_address,
            anchor=row,
            chain=chain,
        )

    async def _verify_on_chain(
        self,
        registry: CommitmentRegistry,
        expected: str | None,
        row: AuditBatchAnchor | None,
    ) -> ChainVerification:
        def result(status: ChainVerificationStatus, block: int | None = None) -> ChainVerification:
            return ChainVerification(status, expected, block, self._now())

        if expected is None:
            return result(ChainVerificationStatus.LOCAL_INTEGRITY_FAILED)
        confirmed = row is not None and row.status is ChainAnchorStatus.CONFIRMED
        try:
            block = await registry.anchored_block(expected)
            if block == 0:
                status = (
                    ChainVerificationStatus.MISMATCH
                    if confirmed
                    else ChainVerificationStatus.NOT_ON_CHAIN
                )
                return result(status)
            if row is not None and confirmed:
                if (
                    row.commitment != expected
                    or row.block_number != block
                    or row.contract_address.lower() != registry.contract_address.lower()
                    or row.tx_hash is None
                ):
                    return result(ChainVerificationStatus.MISMATCH, block)
                receipt = await registry.get_receipt(row.tx_hash)
                if (
                    receipt is None
                    or not receipt.succeeded
                    or receipt.block_number != block
                    or not receipt.records_commitment(
                        contract_address=registry.contract_address, commitment=expected
                    )
                ):
                    return result(ChainVerificationStatus.MISMATCH, block)
        except ChainError:
            return result(ChainVerificationStatus.UNAVAILABLE)
        return result(ChainVerificationStatus.VERIFIED, block)
