"""API request and response schemas for notifications module (ADR-031)."""

from datetime import datetime
from uuid import UUID

from app.modules.notifications.models import NotificationEventType
from app.shared.schemas import ApiModel


class NotificationResponse(ApiModel):
    """Notification representation for client display and routing (ADR-031)."""

    id: UUID
    event_type: NotificationEventType
    title: str
    message: str
    reference_request_id: UUID | None = None
    actor_doctor_id: UUID | None = None
    actor_hospital_id: UUID | None = None
    is_read: bool
    read_at: datetime | None = None
    created_at: datetime


class NotificationListResponse(ApiModel):
    """Keyset-paginated list of notifications."""

    items: list[NotificationResponse]
    next_cursor: str | None = None


class UnreadCountResponse(ApiModel):
    """Count of unread notifications for the caller."""

    count: int


class MarkAllReadResponse(ApiModel):
    """Count of notifications newly marked as read."""

    count: int
