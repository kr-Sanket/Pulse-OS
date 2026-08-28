"""Audit domain service: append-only event logging, canonical hashing, and integrity verification.

Framework-free; owns no transaction — the request scope commits (app/core/db.py).
Cross-module boundaries use explicit service interfaces (auth, patients).

CORE SECURITY INVARIANT:
Audit events are written in the same transaction as the action they record (ADR-004).
PostgreSQL is authoritative; blockchain anchoring provides asynchronous tamper-evidence.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.modules.audit.anchor import (
    AuditAnchor,
    DbAuditAnchor,
    compute_canonical_hash,
)
from app.modules.audit.errors import (
    AuditEventNotFoundError,
    AuditValidationError,
)
from app.modules.audit.models import AnchorStatus, AuditAction, AuditEvent
from app.modules.audit.repository import AuditEventRepository
from app.modules.auth.accounts import UserAccountService
from app.modules.auth.domain import Role
from app.modules.patients.service import PatientService


class AuditService:
    def __init__(
        self,
        audit: AuditEventRepository,
        accounts: UserAccountService,
        patients: PatientService,
        anchor: AuditAnchor | None = None,
    ) -> None:
        self._audit = audit
        self._accounts = accounts
        self._patients = patients
        self._anchor: AuditAnchor = anchor or DbAuditAnchor()

    async def record_event(
        self,
        *,
        actor_id: UUID,
        actor_role: Role,
        action: AuditAction,
        patient_id: UUID,
        target_id: UUID | None = None,
        target_type: str | None = None,
        request_context: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
        auto_anchor: bool = False,
    ) -> AuditEvent:
        """Record an append-only audit event, calculate its canonical hash, and persist it."""
        actor = await self._accounts.get_by_id(actor_id)
        if actor is None:
            raise AuditValidationError("Actor user does not exist.")

        patient = await self._patients.get_patient_by_id(patient_id)
        if patient is None:
            raise AuditValidationError("Subject patient does not exist.")

        event_timestamp = timestamp or datetime.now(UTC)
        if event_timestamp.tzinfo is None:
            event_timestamp = event_timestamp.replace(tzinfo=UTC)

        clean_context = dict(request_context) if request_context is not None else None

        canonical_hash = compute_canonical_hash(
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            patient_id=patient_id,
            target_id=target_id,
            target_type=target_type,
            timestamp=event_timestamp,
            request_context=clean_context,
        )

        event = AuditEvent(
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            patient_id=patient_id,
            target_id=target_id,
            target_type=target_type,
            timestamp=event_timestamp,
            request_context=clean_context,
            canonical_hash=canonical_hash,
            anchor_status=AnchorStatus.PENDING,
        )

        persisted = await self._audit.add(event)

        if auto_anchor:
            receipt = await self._anchor.anchor(persisted)
            updated = await self._audit.update_anchor_status(
                id=persisted.id,
                status=receipt.status,
                tx_hash=receipt.tx_hash,
                anchored_at=receipt.anchored_at,
            )
            if updated is not None:
                return updated

        return persisted

    async def get_event(self, event_id: UUID) -> AuditEvent | None:
        return await self._audit.get_by_id(event_id)

    async def list_events_for_patient(
        self, patient_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> Sequence[AuditEvent]:
        return await self._audit.list_by_patient_id(patient_id, limit=limit, offset=offset)

    async def list_events_for_actor(
        self, actor_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> Sequence[AuditEvent]:
        return await self._audit.list_by_actor_id(actor_id, limit=limit, offset=offset)

    async def verify_event_integrity(self, event_id: UUID) -> bool:
        """Recompute canonical hash from stored event attributes and detect tampering (RC-2)."""
        event = await self._audit.get_by_id(event_id)
        if event is None:
            raise AuditEventNotFoundError("Audit event not found.")

        recomputed_hash = compute_canonical_hash(
            actor_id=event.actor_id,
            actor_role=event.actor_role,
            action=event.action,
            patient_id=event.patient_id,
            target_id=event.target_id,
            target_type=event.target_type,
            timestamp=event.timestamp,
            request_context=event.request_context,
        )
        return recomputed_hash == event.canonical_hash
