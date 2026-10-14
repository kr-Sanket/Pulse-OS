"""notifications-owned tables (ADR-031).

Conventions match the other modules: UUID primary keys, enum columns as non-native VARCHAR
with the *values* persisted (so extending a vocabulary never requires a constraint migration),
no relationship() anywhere, and cross-module links as plain UUID foreign keys — referential
integrity only, never an ORM graph crossing a module boundary (docs/SYSTEM_ARCHITECTURE.md rule 1).

Three invariants shape the tables below:

1. **Transactional atomicity with consent mutations.** Notifications are written within the same
   request-scoped transaction as the triggering consent action
   (docs/SYSTEM_ARCHITECTURE.md, ADR-031). If a consent change fails or rolls back, its
   notification rolls back with it.

2. **Recipient isolation and tombstone deletion.** Notifications belong to an authenticated user
   (``recipient_user_id`` referencing ``users.id``). In accordance with PulseOS's
   identity-retention and tombstone conventions (docs/DATABASE_DESIGN.md principle 5),
   no ``ON DELETE CASCADE`` is used.

3. **Generic copy and structured references.** Notification messages contain generic administrative
   copy with zero PHI, zero clinical categories, and zero health identifiers. Minimal foreign
   keys (``reference_request_id``, ``actor_doctor_id``, ``actor_hospital_id``) are stored to
   enable client routing; navigation to these references always executes full role and consent
   authorization.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _enum_values(enum_cls: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_cls]


class NotificationEventType(StrEnum):
    """Consent lifecycle events that trigger an in-app notification (ADR-031)."""

    ACCESS_REQUESTED = "ACCESS_REQUESTED"
    CONSENT_APPROVED = "CONSENT_APPROVED"
    CONSENT_REJECTED = "CONSENT_REJECTED"
    CONSENT_REVOKED = "CONSENT_REVOKED"


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An in-app notification delivered to a patient or doctor (ADR-031).

    Mutable by design: ``is_read`` and ``read_at`` transition when the user acknowledges
    the notification, which is why this table uses ``TimestampMixin`` rather than an
    append-only timestamp.

    Notifications are convenience records, not audit evidence. Authoritative audit history
    remains ``audit_logs`` (ADR-027). Notifications may be marked read or pruned under
    retention policies without affecting audit integrity.
    """

    __tablename__ = "notifications"

    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id"), nullable=False
    )
    event_type: Mapped[NotificationEventType] = mapped_column(
        Enum(
            NotificationEventType,
            name="notification_event_type",
            native_enum=False,
            length=32,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    message: Mapped[str] = mapped_column(String(255), nullable=False)
    reference_request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("consent_requests.id", ondelete="SET NULL"), nullable=True
    )
    actor_doctor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True
    )
    actor_hospital_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("hospitals.id", ondelete="SET NULL"), nullable=True
    )
    is_read: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Serves unread-count and unread-filtered inbox queries without sorting
        Index(
            "ix_notifications_recipient_unread_created",
            "recipient_user_id",
            "is_read",
            "created_at",
            "id",
        ),
        # Serves standard keyset cursor pagination over all notifications for a user
        Index(
            "ix_notifications_recipient_created",
            "recipient_user_id",
            "created_at",
            "id",
        ),
    )
