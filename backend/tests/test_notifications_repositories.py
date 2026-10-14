"""Repository unit tests for notifications module (ADR-031)."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from app.modules.auth.domain import Role
from app.modules.auth.models import User
from app.modules.notifications.models import Notification, NotificationEventType
from app.modules.notifications.repository import NotificationRepository
from app.shared.pagination import CursorKey

from tests.support import sqlite_session


def test_repository_add_and_get() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            user = User(
                id=uuid.uuid4(),
                firebase_uid="fb_repo_user_1",
                role=Role.PATIENT,
            )
            session.add(user)
            await session.flush()

            repo = NotificationRepository(session)
            notification = Notification(
                recipient_user_id=user.id,
                event_type=NotificationEventType.ACCESS_REQUESTED,
                title="Access Request Received",
                message="A doctor requested access to your health records.",
            )
            saved = await repo.add(notification)
            assert saved.id is not None

            # Retrieve by id and recipient
            fetched = await repo.get_by_id_and_recipient(saved.id, user.id)
            assert fetched is not None
            assert fetched.id == saved.id
            assert fetched.title == "Access Request Received"

            # Retrieve by wrong recipient returns None
            other_user_id = uuid.uuid4()
            assert await repo.get_by_id_and_recipient(saved.id, other_user_id) is None

    asyncio.run(scenario())


def test_repository_keyset_pagination_and_ordering() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            user = User(
                id=uuid.uuid4(),
                firebase_uid="fb_repo_user_2",
                role=Role.DOCTOR,
            )
            other_user = User(
                id=uuid.uuid4(),
                firebase_uid="fb_repo_user_other",
                role=Role.DOCTOR,
            )
            session.add_all([user, other_user])
            await session.flush()

            repo = NotificationRepository(session)
            base_time = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)

            # Insert 5 notifications for user with increasing timestamps
            notifs = []
            for i in range(5):
                n = Notification(
                    recipient_user_id=user.id,
                    event_type=NotificationEventType.CONSENT_APPROVED,
                    title=f"Notification {i}",
                    message=f"Message {i}",
                    created_at=base_time + timedelta(minutes=i * 10),
                )
                session.add(n)
                notifs.append(n)

            # Insert 1 notification for other_user to ensure isolation
            session.add(
                Notification(
                    recipient_user_id=other_user.id,
                    event_type=NotificationEventType.CONSENT_APPROVED,
                    title="Other's notification",
                    message="Other's message",
                )
            )
            await session.flush()

            # Page 1: limit 2 -> newest first (notif 4, notif 3)
            page1 = await repo.list_page_by_recipient(user.id, after=None, limit=2)
            assert len(page1) == 2
            assert page1[0].title == "Notification 4"
            assert page1[1].title == "Notification 3"

            cursor1 = CursorKey(created_at=page1[1].created_at, item_id=page1[1].id)

            # Page 2: limit 2 after cursor1 -> (notif 2, notif 1)
            page2 = await repo.list_page_by_recipient(user.id, after=cursor1, limit=2)
            assert len(page2) == 2
            assert page2[0].title == "Notification 2"
            assert page2[1].title == "Notification 1"

            cursor2 = CursorKey(created_at=page2[1].created_at, item_id=page2[1].id)

            # Page 3: limit 2 after cursor2 -> (notif 0)
            page3 = await repo.list_page_by_recipient(user.id, after=cursor2, limit=2)
            assert len(page3) == 1
            assert page3[0].title == "Notification 0"

            cursor3 = CursorKey(created_at=page3[0].created_at, item_id=page3[0].id)

            # Terminal page: empty
            page4 = await repo.list_page_by_recipient(user.id, after=cursor3, limit=2)
            assert len(page4) == 0

    asyncio.run(scenario())


def test_repository_ordering_with_identical_timestamps() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            user = User(
                id=uuid.uuid4(),
                firebase_uid="fb_repo_user_tie",
                role=Role.PATIENT,
            )
            session.add(user)
            await session.flush()

            repo = NotificationRepository(session)
            same_time = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)

            # Fix UUIDs so tie-breaker order is deterministic
            id_small = uuid.UUID("00000000-0000-0000-0000-000000000001")
            id_large = uuid.UUID("00000000-0000-0000-0000-000000000002")

            n1 = Notification(
                id=id_small,
                recipient_user_id=user.id,
                event_type=NotificationEventType.ACCESS_REQUESTED,
                title="Small ID",
                message="Msg",
                created_at=same_time,
            )
            n2 = Notification(
                id=id_large,
                recipient_user_id=user.id,
                event_type=NotificationEventType.ACCESS_REQUESTED,
                title="Large ID",
                message="Msg",
                created_at=same_time,
            )
            session.add_all([n1, n2])
            await session.flush()

            # (created_at DESC, id DESC) -> n2 then n1
            page = await repo.list_page_by_recipient(user.id, after=None, limit=2)
            assert [x.id for x in page] == [id_large, id_small]

            cursor = CursorKey(created_at=same_time, item_id=id_large)
            page_after = await repo.list_page_by_recipient(user.id, after=cursor, limit=2)
            assert len(page_after) == 1
            assert page_after[0].id == id_small

    asyncio.run(scenario())


def test_repository_unread_only_filtering_and_counts() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            user = User(
                id=uuid.uuid4(),
                firebase_uid="fb_repo_user_unread",
                role=Role.PATIENT,
            )
            session.add(user)
            await session.flush()

            repo = NotificationRepository(session)
            n_unread = Notification(
                recipient_user_id=user.id,
                event_type=NotificationEventType.ACCESS_REQUESTED,
                title="Unread",
                message="Msg",
                is_read=False,
            )
            n_read = Notification(
                recipient_user_id=user.id,
                event_type=NotificationEventType.CONSENT_APPROVED,
                title="Read",
                message="Msg",
                is_read=True,
                read_at=datetime.now(UTC),
            )
            session.add_all([n_unread, n_read])
            await session.flush()

            assert await repo.count_unread_by_recipient(user.id) == 1

            all_items = await repo.list_page_by_recipient(
                user.id, after=None, limit=10, unread_only=False
            )
            assert len(all_items) == 2

            unread_items = await repo.list_page_by_recipient(
                user.id, after=None, limit=10, unread_only=True
            )
            assert len(unread_items) == 1
            assert unread_items[0].id == n_unread.id

    asyncio.run(scenario())


def test_repository_mark_as_read_and_mark_all_read() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            user1 = User(id=uuid.uuid4(), firebase_uid="fb_u1", role=Role.PATIENT)
            user2 = User(id=uuid.uuid4(), firebase_uid="fb_u2", role=Role.PATIENT)
            session.add_all([user1, user2])
            await session.flush()

            repo = NotificationRepository(session)
            now = datetime(2026, 10, 13, 0, 0, 0, tzinfo=UTC)

            n1 = Notification(
                recipient_user_id=user1.id,
                event_type=NotificationEventType.ACCESS_REQUESTED,
                title="1",
                message="1",
            )
            n2 = Notification(
                recipient_user_id=user1.id,
                event_type=NotificationEventType.ACCESS_REQUESTED,
                title="2",
                message="2",
            )
            n_other = Notification(
                recipient_user_id=user2.id,
                event_type=NotificationEventType.ACCESS_REQUESTED,
                title="O",
                message="O",
            )
            session.add_all([n1, n2, n_other])
            await session.flush()

            # Mark single read
            marked = await repo.mark_as_read(n1.id, user1.id, read_at=now)
            assert marked is not None
            assert marked.is_read is True
            assert marked.read_at == now

            # Idempotent: already read
            later = now + timedelta(hours=1)
            marked_again = await repo.mark_as_read(n1.id, user1.id, read_at=later)
            assert marked_again is not None
            assert marked_again.read_at == now  # Preserves initial read_at

            # Mark for wrong recipient returns None
            assert await repo.mark_as_read(n1.id, user2.id, read_at=now) is None

            # Mark all read for user1
            assert await repo.count_unread_by_recipient(user1.id) == 1
            assert await repo.count_unread_by_recipient(user2.id) == 1

            count = await repo.mark_all_read_by_recipient(user1.id, read_at=now)
            assert count == 1
            assert await repo.count_unread_by_recipient(user1.id) == 0
            # user2 remains untouched
            assert await repo.count_unread_by_recipient(user2.id) == 1

    asyncio.run(scenario())
