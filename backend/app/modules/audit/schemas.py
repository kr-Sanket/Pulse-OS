"""Audit API schemas — camelCase wire shapes (docs/API_GUIDELINES.md)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.audit.models import AnchorStatus, AuditAction
from app.modules.auth.domain import Role
from app.shared.schemas import ApiModel


class AuditEventRead(ApiModel):
    id: UUID
    actor_id: UUID
    actor_role: Role
    action: AuditAction
    patient_id: UUID
    target_id: UUID | None
    target_type: str | None
    timestamp: datetime
    request_context: dict[str, Any] | None
    canonical_hash: str
    anchor_status: AnchorStatus
    anchor_tx_hash: str | None
    anchored_at: datetime | None


class AnchorReceiptRead(ApiModel):
    event_id: UUID
    canonical_hash: str
    tx_hash: str | None
    anchored_at: datetime
    status: AnchorStatus
