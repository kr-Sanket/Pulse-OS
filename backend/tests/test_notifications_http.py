"""HTTP endpoint tests for notifications module (ADR-031)."""

import asyncio
import uuid
from collections.abc import AsyncGenerator

from app.core.db import Base, get_db_session
from app.core.ratelimit import UnlimitedRateLimiter, get_rate_limiter
from app.main import create_app
from app.modules.auth.dependencies import get_auth_provider
from app.modules.auth.domain import Role
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.models import User
from app.modules.notifications.models import Notification, NotificationEventType
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.support import create_sqlite_test_engine


def _setup_app_and_client() -> tuple[FastAPI, FakeAuthProvider, async_sessionmaker[AsyncSession]]:
    app: FastAPI = create_app()
    engine = create_sqlite_test_engine()

    async def _schema() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(_schema())

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session, session.begin():
            yield session

    fake_auth = FakeAuthProvider()
    app.dependency_overrides[get_db_session] = _override_get_db_session
    app.dependency_overrides[get_auth_provider] = lambda: fake_auth
    app.dependency_overrides[get_rate_limiter] = lambda: UnlimitedRateLimiter()

    return app, fake_auth, session_factory


def test_notifications_role_gates_and_auth() -> None:
    app, fake_auth, session_factory = _setup_app_and_client()

    patient_user_id = uuid.uuid4()
    doctor_user_id = uuid.uuid4()
    hadmin_user_id = uuid.uuid4()
    sadmin_user_id = uuid.uuid4()

    async def _seed() -> None:
        async with session_factory() as session, session.begin():
            session.add_all(
                [
                    User(id=patient_user_id, firebase_uid="fb_patient", role=Role.PATIENT),
                    User(id=doctor_user_id, firebase_uid="fb_doctor", role=Role.DOCTOR),
                    User(id=hadmin_user_id, firebase_uid="fb_hadmin", role=Role.HOSPITAL_ADMIN),
                    User(id=sadmin_user_id, firebase_uid="fb_sadmin", role=Role.SYSTEM_ADMIN),
                ]
            )

    asyncio.run(_seed())

    fake_auth.register_user(
        "tok_patient",
        user_id=patient_user_id,
        firebase_uid="fb_patient",
        role=Role.PATIENT,
    )
    fake_auth.register_user(
        "tok_doctor",
        user_id=doctor_user_id,
        firebase_uid="fb_doctor",
        role=Role.DOCTOR,
    )
    fake_auth.register_user(
        "tok_hadmin",
        user_id=hadmin_user_id,
        firebase_uid="fb_hadmin",
        role=Role.HOSPITAL_ADMIN,
    )
    fake_auth.register_user(
        "tok_sadmin",
        user_id=sadmin_user_id,
        firebase_uid="fb_sadmin",
        role=Role.SYSTEM_ADMIN,
    )

    with TestClient(app) as client:
        # Unauthenticated -> 401
        res = client.get("/api/v1/notifications")
        assert res.status_code == 401

        # SYSTEM_ADMIN -> 403
        res = client.get("/api/v1/notifications", headers={"Authorization": "Bearer tok_sadmin"})
        assert res.status_code == 403

        # HOSPITAL_ADMIN -> 403
        res = client.get("/api/v1/notifications", headers={"Authorization": "Bearer tok_hadmin"})
        assert res.status_code == 403

        # PATIENT -> 200
        res = client.get("/api/v1/notifications", headers={"Authorization": "Bearer tok_patient"})
        assert res.status_code == 200
        assert res.json() == {"items": [], "nextCursor": None}

        # DOCTOR -> 200
        res = client.get("/api/v1/notifications", headers={"Authorization": "Bearer tok_doctor"})
        assert res.status_code == 200
        assert res.json() == {"items": [], "nextCursor": None}


def test_notifications_crud_and_cross_user_isolation() -> None:
    app, fake_auth, session_factory = _setup_app_and_client()

    patient_id = uuid.uuid4()
    doctor_id = uuid.uuid4()
    notif_id = uuid.uuid4()

    async def _seed() -> None:
        async with session_factory() as session, session.begin():
            session.add_all(
                [
                    User(id=patient_id, firebase_uid="fb_p1", role=Role.PATIENT),
                    User(id=doctor_id, firebase_uid="fb_d1", role=Role.DOCTOR),
                ]
            )
            # Notification belongs to patient
            session.add(
                Notification(
                    id=notif_id,
                    recipient_user_id=patient_id,
                    event_type=NotificationEventType.ACCESS_REQUESTED,
                    title="Access Request Received",
                    message="A doctor requested access to your health records.",
                )
            )

    asyncio.run(_seed())

    fake_auth.register_user(
        "tok_p1",
        user_id=patient_id,
        firebase_uid="fb_p1",
        role=Role.PATIENT,
    )
    fake_auth.register_user(
        "tok_d1",
        user_id=doctor_id,
        firebase_uid="fb_d1",
        role=Role.DOCTOR,
    )

    with TestClient(app) as client:
        # Patient sees 1 unread notification
        res = client.get(
            "/api/v1/notifications/unread-count",
            headers={"Authorization": "Bearer tok_p1"},
        )
        assert res.status_code == 200
        assert res.json() == {"count": 1}

        # Doctor sees 0 unread notifications (recipient isolation)
        res = client.get(
            "/api/v1/notifications/unread-count",
            headers={"Authorization": "Bearer tok_d1"},
        )
        assert res.status_code == 200
        assert res.json() == {"count": 0}

        # Doctor attempts to read Patient's notification -> 404 (not 403!)
        res = client.post(
            f"/api/v1/notifications/{notif_id}/read",
            headers={"Authorization": "Bearer tok_d1"},
        )
        assert res.status_code == 404
        assert res.json()["detail"] == "Notification not found."

        # Patient reads own notification -> 200 with camelCase schema
        res = client.post(
            f"/api/v1/notifications/{notif_id}/read",
            headers={"Authorization": "Bearer tok_p1"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["id"] == str(notif_id)
        assert body["eventType"] == "ACCESS_REQUESTED"
        assert body["title"] == "Access Request Received"
        assert body["message"] == "A doctor requested access to your health records."
        assert body["isRead"] is True
        assert body["readAt"] is not None
        assert "referenceRequestId" in body
        assert "actorDoctorId" in body
        assert "actorHospitalId" in body
        assert "createdAt" in body
        # Ensure no disallowed / sensitive fields leak
        assert "patientName" not in body
        assert "healthId" not in body

        # Unread count is now 0 for patient
        res = client.get(
            "/api/v1/notifications/unread-count",
            headers={"Authorization": "Bearer tok_p1"},
        )
        assert res.json() == {"count": 0}


def test_notifications_mark_all_read_and_pagination() -> None:
    app, fake_auth, session_factory = _setup_app_and_client()

    patient_id = uuid.uuid4()

    async def _seed() -> None:
        async with session_factory() as session, session.begin():
            session.add(User(id=patient_id, firebase_uid="fb_p_bulk", role=Role.PATIENT))
            for i in range(5):
                session.add(
                    Notification(
                        recipient_user_id=patient_id,
                        event_type=NotificationEventType.CONSENT_APPROVED,
                        title=f"Notification {i}",
                        message=f"Message {i}",
                        is_read=False,
                    )
                )

    asyncio.run(_seed())

    fake_auth.register_user(
        "tok_bulk",
        user_id=patient_id,
        firebase_uid="fb_p_bulk",
        role=Role.PATIENT,
    )

    with TestClient(app) as client:
        # Invalid cursor returns 422
        res = client.get(
            "/api/v1/notifications?cursor=invalid_base64_not_cursor",
            headers={"Authorization": "Bearer tok_bulk"},
        )
        assert res.status_code == 422
        assert res.json()["detail"] == "Invalid pagination cursor."

        # Pagination with limit=2
        res = client.get(
            "/api/v1/notifications?limit=2",
            headers={"Authorization": "Bearer tok_bulk"},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data["items"]) == 2
        assert data["nextCursor"] is not None

        # Fetch next page using cursor
        cursor = data["nextCursor"]
        res2 = client.get(
            f"/api/v1/notifications?limit=2&cursor={cursor}",
            headers={"Authorization": "Bearer tok_bulk"},
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert len(data2["items"]) == 2
        assert data2["nextCursor"] is not None

        # Mark all read
        res_bulk = client.post(
            "/api/v1/notifications/mark-all-read",
            headers={"Authorization": "Bearer tok_bulk"},
        )
        assert res_bulk.status_code == 200
        assert res_bulk.json() == {"count": 5}

        # Filter by unreadOnly=true -> 0 items
        res_unread = client.get(
            "/api/v1/notifications?unreadOnly=true",
            headers={"Authorization": "Bearer tok_bulk"},
        )
        assert res_unread.status_code == 200
        assert len(res_unread.json()["items"]) == 0
