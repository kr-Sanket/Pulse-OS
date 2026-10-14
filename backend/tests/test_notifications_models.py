"""Tests for Notification and NotificationEventType models (ADR-031)."""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from app.modules.auth.domain import Role
from app.modules.auth.models import User
from app.modules.notifications.models import Notification, NotificationEventType
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tests.support import sqlite_session


def test_notification_event_type_values() -> None:
    assert NotificationEventType.ACCESS_REQUESTED == "ACCESS_REQUESTED"
    assert NotificationEventType.CONSENT_APPROVED == "CONSENT_APPROVED"
    assert NotificationEventType.CONSENT_REJECTED == "CONSENT_REJECTED"
    assert NotificationEventType.CONSENT_REVOKED == "CONSENT_REVOKED"
    assert set(NotificationEventType) == {
        NotificationEventType.ACCESS_REQUESTED,
        NotificationEventType.CONSENT_APPROVED,
        NotificationEventType.CONSENT_REJECTED,
        NotificationEventType.CONSENT_REVOKED,
    }


def test_create_and_retrieve_notification() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            user = User(
                id=uuid.uuid4(),
                firebase_uid="fb_test_user_1",
                phone="+919876543210",
                role=Role.PATIENT,
            )
            session.add(user)
            await session.flush()

            notification = Notification(
                recipient_user_id=user.id,
                event_type=NotificationEventType.ACCESS_REQUESTED,
                title="Access Request Received",
                message="A doctor requested access to your health records.",
            )
            session.add(notification)
            await session.flush()

            assert notification.id is not None
            assert notification.recipient_user_id == user.id
            assert notification.event_type == NotificationEventType.ACCESS_REQUESTED
            assert notification.title == "Access Request Received"
            assert notification.message == "A doctor requested access to your health records."
            assert notification.is_read is False
            assert notification.read_at is None
            assert notification.reference_request_id is None
            assert notification.actor_doctor_id is None
            assert notification.actor_hospital_id is None
            assert notification.created_at is not None
            assert notification.updated_at is not None

            # Re-fetch from DB
            stmt = select(Notification).where(Notification.id == notification.id)
            saved = (await session.execute(stmt)).scalar_one()
            assert saved.title == "Access Request Received"
            assert saved.is_read is False

    asyncio.run(scenario())


def test_notification_with_structured_references() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            doctor_user = User(
                id=uuid.uuid4(),
                firebase_uid="fb_test_doc_user",
                phone="+919876543211",
                role=Role.DOCTOR,
            )
            patient_user = User(
                id=uuid.uuid4(),
                firebase_uid="fb_test_pat_user",
                phone="+919876543212",
                role=Role.PATIENT,
            )
            session.add_all([doctor_user, patient_user])
            await session.flush()

            from app.modules.consent.models import ConsentRequest, ConsentRequestStatus
            from app.modules.patients.models import Patient
            from app.modules.records.models import (
                Doctor,
                DoctorStatus,
                Hospital,
                HospitalVerificationStatus,
            )

            hospital = Hospital(
                hid="HID-TEST-NOTIF",
                name="Notif Hospital",
                verification_status=HospitalVerificationStatus.VERIFIED,
            )
            session.add(hospital)
            await session.flush()

            doctor = Doctor(
                user_id=doctor_user.id,
                hospital_id=hospital.id,
                full_name="Dr Notif",
                registration_number="NOTIF-R1",
                status=DoctorStatus.ACTIVE,
            )
            patient = Patient(
                user_id=patient_user.id,
                health_id="PHI-IND-2026-NOTIF01",
                full_name="Patient Notif",
            )
            session.add_all([doctor, patient])
            await session.flush()

            consent_request = ConsentRequest(
                patient_id=patient.id,
                requester_doctor_id=doctor.id,
                requester_hospital_id=hospital.id,
                purpose="Consultation",
                status=ConsentRequestStatus.PENDING,
                expires_at=datetime.now(UTC),
            )
            session.add(consent_request)
            await session.flush()

            notification = Notification(
                recipient_user_id=doctor_user.id,
                event_type=NotificationEventType.CONSENT_APPROVED,
                title="Access Request Approved",
                message="A patient approved your record access request.",
                reference_request_id=consent_request.id,
                actor_doctor_id=doctor.id,
                actor_hospital_id=hospital.id,
            )
            session.add(notification)
            await session.flush()

            stmt = select(Notification).where(Notification.recipient_user_id == doctor_user.id)
            saved = (await session.execute(stmt)).scalar_one()
            assert saved.reference_request_id == consent_request.id
            assert saved.actor_doctor_id == doctor.id
            assert saved.actor_hospital_id == hospital.id

    asyncio.run(scenario())


def test_update_notification_read_status() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            user = User(
                id=uuid.uuid4(),
                firebase_uid="fb_test_user_3",
                phone="+919876543212",
                role=Role.PATIENT,
            )
            session.add(user)
            await session.flush()

            notification = Notification(
                recipient_user_id=user.id,
                event_type=NotificationEventType.CONSENT_REVOKED,
                title="Consent Grant Revoked",
                message="A consent grant for patient records was revoked.",
            )
            session.add(notification)
            await session.flush()

            assert notification.is_read is False
            assert notification.read_at is None

            read_time = datetime.now(UTC)
            notification.is_read = True
            notification.read_at = read_time
            await session.flush()

            stmt = select(Notification).where(Notification.id == notification.id)
            updated = (await session.execute(stmt)).scalar_one()
            assert updated.is_read is True
            assert updated.read_at is not None

    asyncio.run(scenario())


def test_notification_foreign_key_to_user_enforced() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            non_existent_user_id = uuid.uuid4()
            notification = Notification(
                recipient_user_id=non_existent_user_id,
                event_type=NotificationEventType.ACCESS_REQUESTED,
                title="Access Request Received",
                message="A doctor requested access to your health records.",
            )
            session.add(notification)
            with pytest.raises(IntegrityError):
                await session.flush()

    asyncio.run(scenario())


def test_notification_recipient_user_deletion_does_not_cascade() -> None:
    """Recipient user deletion must fail via RESTRICT/NO ACTION integrity check, not cascade."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            user = User(
                id=uuid.uuid4(),
                firebase_uid="fb_test_del_user",
                phone="+919876543299",
                role=Role.PATIENT,
            )
            session.add(user)
            await session.flush()

            notification = Notification(
                recipient_user_id=user.id,
                event_type=NotificationEventType.ACCESS_REQUESTED,
                title="Access Request Received",
                message="A doctor requested access to your health records.",
            )
            session.add(notification)
            await session.flush()

            # Attempting to delete the user must raise IntegrityError because there is NO cascade
            await session.delete(user)
            with pytest.raises(IntegrityError):
                await session.flush()

    asyncio.run(scenario())


def test_notification_structured_references_set_null_on_delete() -> None:
    """Deleting referenced consent_request, doctor, or hospital nullifies the foreign key."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            doctor_user = User(
                id=uuid.uuid4(),
                firebase_uid="fb_test_doc_ref_del",
                phone="+919876543288",
                role=Role.DOCTOR,
            )
            patient_user = User(
                id=uuid.uuid4(),
                firebase_uid="fb_test_pat_ref_del",
                phone="+919876543287",
                role=Role.PATIENT,
            )
            session.add_all([doctor_user, patient_user])
            await session.flush()

            from app.modules.consent.models import ConsentRequest, ConsentRequestStatus
            from app.modules.patients.models import Patient
            from app.modules.records.models import (
                Doctor,
                DoctorStatus,
                Hospital,
                HospitalVerificationStatus,
            )

            hospital = Hospital(
                hid="HID-TEST-REF-DEL",
                name="Ref Del Hospital",
                verification_status=HospitalVerificationStatus.VERIFIED,
            )
            session.add(hospital)
            await session.flush()

            doctor = Doctor(
                user_id=doctor_user.id,
                hospital_id=hospital.id,
                full_name="Dr Ref Del",
                registration_number="REF-DEL-R1",
                status=DoctorStatus.ACTIVE,
            )
            patient = Patient(
                user_id=patient_user.id,
                health_id="PHI-IND-2026-REF-DEL-01",
                full_name="Patient Ref Del",
            )
            session.add_all([doctor, patient])
            await session.flush()

            consent_request = ConsentRequest(
                patient_id=patient.id,
                requester_doctor_id=doctor.id,
                requester_hospital_id=hospital.id,
                purpose="Consultation",
                status=ConsentRequestStatus.PENDING,
                expires_at=datetime.now(UTC),
            )
            session.add(consent_request)
            await session.flush()

            notification = Notification(
                recipient_user_id=doctor_user.id,
                event_type=NotificationEventType.CONSENT_APPROVED,
                title="Access Request Approved",
                message="A patient approved your record access request.",
                reference_request_id=consent_request.id,
                actor_doctor_id=doctor.id,
                actor_hospital_id=hospital.id,
            )
            session.add(notification)
            await session.flush()

            # Deleting the consent_request should trigger ON DELETE SET NULL on reference_request_id
            await session.delete(consent_request)
            await session.flush()

            # Expire/refresh notification to inspect DB state
            await session.refresh(notification)
            assert notification.reference_request_id is None
            assert notification.actor_doctor_id == doctor.id
            assert notification.actor_hospital_id == hospital.id

    asyncio.run(scenario())
