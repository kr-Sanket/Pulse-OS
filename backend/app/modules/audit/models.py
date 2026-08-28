"""audit-owned tables (docs/DOMAIN_MODEL.md §1: AuditEvent, FHIR AuditEvent-aligned).

Append-only audit trail (ADR-004, docs/SECURITY.md).
Immutable historical events; canonical JSON hashing; pluggable anchor support.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKeyMixin
from app.modules.auth.domain import Role


class AuditAction(StrEnum):
    """Authoritative audit action vocabulary (docs/DOMAIN_MODEL.md §1)."""

    RECORD_UPLOADED = "RECORD_UPLOADED"
    ACCESS_REQUESTED = "ACCESS_REQUESTED"
    CONSENT_APPROVED = "CONSENT_APPROVED"
    CONSENT_REJECTED = "CONSENT_REJECTED"
    CONSENT_REVOKED = "CONSENT_REVOKED"
    RECORD_VIEWED = "RECORD_VIEWED"
    RECORD_DOWNLOADED = "RECORD_DOWNLOADED"
    SUMMARY_GENERATED = "SUMMARY_GENERATED"


class AnchorStatus(StrEnum):
    """Lifecycle status of blockchain/database hash anchoring (ADR-004)."""

    PENDING = "PENDING"
    ANCHORED = "ANCHORED"
    FAILED = "FAILED"


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only audit event record.
    Captures actor, action, subject patient, target, timestamp, request context,
    and canonical hash for tamper evidence (ADR-004).
    """

    __tablename__ = "audit_events"

    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id"), nullable=False, index=True
    )
    actor_role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            name="audit_actor_role",
            native_enum=False,
            length=30,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    action: Mapped[AuditAction] = mapped_column(
        Enum(
            AuditAction,
            name="audit_action",
            native_enum=False,
            length=50,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("patients.id"), nullable=False, index=True
    )
    target_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True, index=True)
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    request_context: Mapped[dict[str, Any] | None] = mapped_column(JSON(), nullable=True)
    canonical_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    anchor_status: Mapped[AnchorStatus] = mapped_column(
        Enum(
            AnchorStatus,
            name="anchor_status",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=AnchorStatus.PENDING,
    )
    anchor_tx_hash: Mapped[str | None] = mapped_column(String(100), nullable=True)
    anchored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
