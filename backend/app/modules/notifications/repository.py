"""Persistence for notifications-owned tables (ADR-031).

Conventions match the other modules: takes an AsyncSession, never commits (the
request scope owns the transaction, app/core/db.py), flushes mutations, and uses
keyset-pagination over (created_at DESC, id DESC).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CursorResult, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.modules.notifications.models import Notification
from app.shared.pagination import CursorKey


def _keyset_filter(
    time_col: InstrumentedAttribute[datetime],
    id_col: InstrumentedAttribute[UUID],
    after: CursorKey,
) -> ColumnElement[bool]:
    """WHERE clause for "strictly after after in (time DESC, id DESC) order".

    Spelled as an OR because SQLite lacks tuple comparison. Matches the pattern
    in app/modules/consent/repository.py.
    """
    return or_(
        time_col < after.created_at,
        and_(time_col == after.created_at, id_col < after.item_id),
    )


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, notification: Notification) -> Notification:
        """Add and flush a notification entity."""
        self._session.add(notification)
        await self._session.flush()
        return notification

    async def get_by_id_and_recipient(
        self, notification_id: UUID, recipient_user_id: UUID
    ) -> Notification | None:
        """Find a single notification strictly owned by recipient_user_id."""
        query = select(Notification).where(
            Notification.id == notification_id,
            Notification.recipient_user_id == recipient_user_id,
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def list_page_by_recipient(
        self,
        recipient_user_id: UUID,
        *,
        after: CursorKey | None,
        limit: int,
        unread_only: bool = False,
    ) -> list[Notification]:
        """Fetch limit rows strictly ordered by created_at DESC, id DESC."""
        conditions = [Notification.recipient_user_id == recipient_user_id]
        if unread_only:
            conditions.append(Notification.is_read.is_(False))

        if after is not None:
            conditions.append(_keyset_filter(Notification.created_at, Notification.id, after))

        query = (
            select(Notification)
            .where(*conditions)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(query)
        return list(result.scalars())

    async def count_unread_by_recipient(self, recipient_user_id: UUID) -> int:
        """Count unread notifications belonging to recipient_user_id."""
        query = (
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.recipient_user_id == recipient_user_id,
                Notification.is_read.is_(False),
            )
        )
        result = await self._session.execute(query)
        return int(result.scalar_one() or 0)

    async def mark_as_read(
        self, notification_id: UUID, recipient_user_id: UUID, read_at: datetime
    ) -> Notification | None:
        """Mark a notification read if owned by recipient_user_id.

        If already read, read_at is preserved and the entity is returned.
        """
        notification = await self.get_by_id_and_recipient(notification_id, recipient_user_id)
        if notification is None:
            return None

        if not notification.is_read:
            notification.is_read = True
            notification.read_at = read_at
            await self._session.flush()

        return notification

    async def mark_all_read_by_recipient(self, recipient_user_id: UUID, read_at: datetime) -> int:
        """Bulk-mark all unread notifications read for recipient_user_id in DB without loading."""
        stmt = (
            update(Notification)
            .where(
                Notification.recipient_user_id == recipient_user_id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True, read_at=read_at)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        if isinstance(result, CursorResult):
            return int(result.rowcount or 0)
        return 0
