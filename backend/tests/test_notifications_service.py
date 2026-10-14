"""Service unit tests for notifications module (ADR-031)."""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from app.modules.auth.domain import Role
from app.modules.auth.models import User
from app.modules.notifications.errors import NotificationNotFoundError
from app.modules.notifications.models import Notification, NotificationEventType
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.service import NotificationService
from app.shared.pagination import decode_cursor

from tests.support import sqlite_session


def test_service_ownership_isolation() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            user = User(id=uuid.uuid4(), firebase_uid="fb_svc_user", role=Role.PATIENT)
            other = User(id=uuid.uuid4(), firebase_uid="fb_svc_other", role=Role.PATIENT)
            session.add_all([user, other])
            await session.flush()

            repo = NotificationRepository(session)
            service = NotificationService(repo)

            notif = Notification(
                recipient_user_id=other.id,
                event_type=NotificationEventType.ACCESS_REQUESTED,
                title="Secret",
                message="Only for other",
            )
            session.add(notif)
            await session.flush()

            # Caller user trying to mark other's notification raises NotificationNotFoundError
            with pytest.raises(NotificationNotFoundError):
                await service.mark_read(notif.id, user.id)

            # Non-existent notification raises NotificationNotFoundError
            with pytest.raises(NotificationNotFoundError):
                await service.mark_read(uuid.uuid4(), user.id)

    asyncio.run(scenario())


def test_service_mark_read_and_idempotence() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            user = User(id=uuid.uuid4(), firebase_uid="fb_svc_idem", role=Role.DOCTOR)
            session.add(user)
            await session.flush()

            repo = NotificationRepository(session)
            fixed_time = datetime(2026, 10, 13, 10, 0, 0, tzinfo=UTC)
            service = NotificationService(repo, clock=lambda: fixed_time)

            notif = Notification(
                recipient_user_id=user.id,
                event_type=NotificationEventType.CONSENT_APPROVED,
                title="Approved",
                message="Your request was approved",
            )
            session.add(notif)
            await session.flush()

            marked = await service.mark_read(notif.id, user.id)
            assert marked.is_read is True
            assert marked.read_at == fixed_time

            # Second call is idempotent
            second_marked = await service.mark_read(notif.id, user.id)
            assert second_marked.is_read is True
            assert second_marked.read_at == fixed_time

    asyncio.run(scenario())


def test_service_mark_all_read_count() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            user = User(id=uuid.uuid4(), firebase_uid="fb_svc_all", role=Role.DOCTOR)
            session.add(user)
            await session.flush()

            repo = NotificationRepository(session)
            fixed_time = datetime(2026, 10, 13, 10, 0, 0, tzinfo=UTC)
            service = NotificationService(repo, clock=lambda: fixed_time)

            n1 = Notification(
                recipient_user_id=user.id,
                event_type=NotificationEventType.ACCESS_REQUESTED,
                title="1",
                message="1",
            )
            n2 = Notification(
                recipient_user_id=user.id,
                event_type=NotificationEventType.ACCESS_REQUESTED,
                title="2",
                message="2",
            )
            session.add_all([n1, n2])
            await session.flush()

            count = await service.mark_all_read(user.id)
            assert count == 2

            # Running again yields 0 newly marked rows
            assert await service.mark_all_read(user.id) == 0

    asyncio.run(scenario())


def test_service_pagination_next_cursor_computation() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            user = User(id=uuid.uuid4(), firebase_uid="fb_svc_page", role=Role.PATIENT)
            session.add(user)
            await session.flush()

            repo = NotificationRepository(session)
            service = NotificationService(repo)

            # Insert 3 notifications
            for i in range(3):
                session.add(
                    Notification(
                        recipient_user_id=user.id,
                        event_type=NotificationEventType.ACCESS_REQUESTED,
                        title=f"N{i}",
                        message=f"M{i}",
                    )
                )
            await session.flush()

            # Limit 2 with 3 items in DB -> returns 2 items and a next_cursor
            items, next_cursor = await service.list_notifications(user.id, cursor=None, limit=2)
            assert len(items) == 2
            assert next_cursor is not None
            cursor_key = decode_cursor(next_cursor)
            assert cursor_key.item_id == items[-1].id

            # Limit 2 with 1 item remaining -> returns 1 item and next_cursor is None
            items_page2, next_cursor2 = await service.list_notifications(
                user.id, cursor=cursor_key, limit=2
            )
            assert len(items_page2) == 1
            assert next_cursor2 is None

    asyncio.run(scenario())
