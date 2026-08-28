"""Pluggable audit anchoring interface and canonical JSON hashing (ADR-004).

Postgres is authoritative; the chain provides tamper-evidence asynchronously.
No PHI or personal data is placed into the canonical hash payload (docs/BLOCKCHAIN_ARCHITECTURE.md).
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from app.modules.audit.models import AnchorStatus, AuditAction, AuditEvent
from app.modules.auth.domain import Role


def compute_canonical_json(
    *,
    actor_id: UUID,
    actor_role: Role | str,
    action: AuditAction | str,
    patient_id: UUID,
    target_id: UUID | None,
    target_type: str | None,
    timestamp: datetime,
    request_context: dict[str, Any] | None = None,
) -> str:
    """Serialize an audit event into deterministic canonical JSON (RFC 8785 style).

    - Sorted keys
    - No redundant whitespace (separators=(',', ':'))
    - Clean ISO-8601 timestamps
    - Opaque UUIDs only (zero PHI)
    """
    # Ensure timestamp has UTC representation for stable string formatting
    ts_utc = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=UTC)

    payload = {
        "action": str(action),
        "actor_id": str(actor_id),
        "actor_role": str(actor_role),
        "patient_id": str(patient_id),
        "request_context": request_context or {},
        "target_id": str(target_id) if target_id is not None else None,
        "target_type": target_type,
        "timestamp": ts_utc.isoformat(),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_canonical_hash(
    *,
    actor_id: UUID,
    actor_role: Role | str,
    action: AuditAction | str,
    patient_id: UUID,
    target_id: UUID | None,
    target_type: str | None,
    timestamp: datetime,
    request_context: dict[str, Any] | None = None,
) -> str:
    """Compute deterministic SHA-256 hash of canonical audit event JSON."""
    canonical_json = compute_canonical_json(
        actor_id=actor_id,
        actor_role=actor_role,
        action=action,
        patient_id=patient_id,
        target_id=target_id,
        target_type=target_type,
        timestamp=timestamp,
        request_context=request_context,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AnchorReceipt:
    """Receipt returned upon anchoring an event (ADR-004, docs/BLOCKCHAIN_ARCHITECTURE.md)."""

    event_id: UUID
    canonical_hash: str
    tx_hash: str | None
    anchored_at: datetime
    status: AnchorStatus


class AuditAnchor(Protocol):
    """Pluggable interface for audit event anchoring."""

    async def anchor(self, event: AuditEvent) -> AnchorReceipt: ...

    async def verify(self, event: AuditEvent, receipt: AnchorReceipt) -> bool: ...


class DbAuditAnchor:
    """Local / test database-safe anchor implementation (M3 fallback per ADR-004).
    Computes/validates canonical hash without connecting to external blockchain networks.
    """

    async def anchor(self, event: AuditEvent) -> AnchorReceipt:
        now_utc = datetime.now(UTC)
        return AnchorReceipt(
            event_id=event.id,
            canonical_hash=event.canonical_hash,
            tx_hash=f"db:{event.canonical_hash[:16]}",
            anchored_at=now_utc,
            status=AnchorStatus.ANCHORED,
        )

    async def verify(self, event: AuditEvent, receipt: AnchorReceipt) -> bool:
        computed_hash = compute_canonical_hash(
            actor_id=event.actor_id,
            actor_role=event.actor_role,
            action=event.action,
            patient_id=event.patient_id,
            target_id=event.target_id,
            target_type=event.target_type,
            timestamp=event.timestamp,
            request_context=event.request_context,
        )
        return computed_hash == receipt.canonical_hash == event.canonical_hash
