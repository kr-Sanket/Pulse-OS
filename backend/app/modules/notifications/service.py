"""Domain service for notifications (ADR-031)."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.modules.notifications.errors import NotificationNotFoundError
from app.modules.notifications.models import Notification
from app.modules.notifications.repository import NotificationRepository
from app.shared.pagination import CursorKey, encode_cursor
from app.shared.time import utc_now


class NotificationService:
    def __init__(
        self,
        repository: NotificationRepository,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._clock = clock

    async def list_notifications(
        self,
        recipient_user_id: UUID,
        *,
        cursor: CursorKey | None,
        limit: int,
        unread_only: bool = False,
    ) -> tuple[list[Notification], str | None]:
        """Fetch a page of notifications and compute the next cursor using limit + 1 probe."""
        # Query limit + 1 to check if there is a next page without a separate count query
        rows = await self._repository.list_page_by_recipient(
            recipient_user_id,
            after=cursor,
            limit=limit + 1,
            unread_only=unread_only,
        )

        has_next = len(rows) > limit
        items = rows[:limit]

        next_cursor: str | None = None
        if has_next and items:
            last_item = items[-1]
            next_cursor = encode_cursor(
                CursorKey(created_at=last_item.created_at, item_id=last_item.id)
            )

        return items, next_cursor

    async def get_unread_count(self, recipient_user_id: UUID) -> int:
        """Get the count of unread notifications for a user."""
        return await self._repository.count_unread_by_recipient(recipient_user_id)

    async def mark_read(self, notification_id: UUID, recipient_user_id: UUID) -> Notification:
        """Mark a notification as read.

        Raises NotificationNotFoundError if it does not exist or belongs to another user.
        """
        now = self._clock()
        notification = await self._repository.mark_as_read(
            notification_id, recipient_user_id, read_at=now
        )
        if notification is None:
            raise NotificationNotFoundError()
        return notification

    async def mark_all_read(self, recipient_user_id: UUID) -> int:
        """Mark all unread notifications read for recipient_user_id and return count."""
        now = self._clock()
        return await self._repository.mark_all_read_by_recipient(recipient_user_id, read_at=now)
