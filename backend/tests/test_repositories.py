"""Repository CRUD + integrity-error translation, against in-memory SQLite."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.modules.audit.models import AnchorStatus, AuditAction, AuditEvent
from app.modules.audit.repository import AuditEventRepository
from app.modules.auth.domain import Role
from app.modules.auth.errors import DuplicateUserError
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.consent.models import (
    AccessRequest,
    ConsentDecision,
    ConsentGrant,
    DecisionType,
    RequestStatus,
)
from app.modules.consent.repository import ConsentRepository
from app.modules.doctors.errors import (
    DuplicateDoctorError,
    DuplicateRegistrationNumberError,
)
from app.modules.doctors.models import Doctor
from app.modules.doctors.repository import DoctorRepository
from app.modules.hospitals.errors import DuplicateHospitalIdError
from app.modules.hospitals.models import Hospital
from app.modules.hospitals.repository import HospitalRepository
from app.modules.patients.errors import DuplicateHealthIdError, DuplicatePatientError
from app.modules.patients.models import Patient
from app.modules.patients.repository import PatientRepository
from app.modules.records.errors import DuplicateCategoryCodeError
from app.modules.records.models import (
    MedicalRecord,
    ProcessingStatus,
    RecordCategory,
    RecordOrigin,
)
from app.modules.records.repository import (
    MedicalRecordRepository,
    RecordCategoryRepository,
)

from tests.support import sqlite_session


def test_user_repository_add_and_lookups() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            repo = UserRepository(session)
            user = await repo.add(
                User(firebase_uid="fb-1", role=Role.PATIENT, phone="+911234", email="a@b.c")
            )
            assert user.id is not None

            by_uid = await repo.get_by_firebase_uid("fb-1")
            assert by_uid is not None and by_uid.id == user.id
            by_id = await repo.get_by_id(user.id)
            assert by_id is not None and by_id.firebase_uid == "fb-1"
            assert await repo.get_by_firebase_uid("fb-unknown") is None

    asyncio.run(scenario())


def test_user_repository_translates_duplicate_firebase_uid() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            repo = UserRepository(session)
            await repo.add(User(firebase_uid="fb-1", role=Role.PATIENT))
            with pytest.raises(DuplicateUserError):
                await repo.add(User(firebase_uid="fb-1", role=Role.PATIENT))
            # The savepoint contained the failure: the session must still be usable.
            await repo.add(User(firebase_uid="fb-2", role=Role.DOCTOR))

    asyncio.run(scenario())


def test_patient_repository_add_and_lookup() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            user = await UserRepository(session).add(User(firebase_uid="fb-1", role=Role.PATIENT))
            repo = PatientRepository(session)
            patient = await repo.add(
                Patient(user_id=user.id, health_id="PHI-IND-2026-7K3M99X", full_name="Asha Rao")
            )
            found = await repo.get_by_user_id(user.id)
            assert found is not None and found.id == patient.id
            assert await repo.get_by_user_id(uuid4()) is None

    asyncio.run(scenario())


def test_patient_repository_distinguishes_unique_violations() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            users = UserRepository(session)
            first = await users.add(User(firebase_uid="fb-1", role=Role.PATIENT))
            second = await users.add(User(firebase_uid="fb-2", role=Role.PATIENT))
            repo = PatientRepository(session)
            await repo.add(
                Patient(user_id=first.id, health_id="PHI-IND-2026-7K3M99X", full_name="A")
            )

            with pytest.raises(DuplicateHealthIdError):
                await repo.add(
                    Patient(user_id=second.id, health_id="PHI-IND-2026-7K3M99X", full_name="B")
                )
            with pytest.raises(DuplicatePatientError):
                await repo.add(
                    Patient(user_id=first.id, health_id="PHI-IND-2026-TNE7WRA", full_name="C")
                )
            # Session still usable after both contained failures.
            await repo.add(
                Patient(user_id=second.id, health_id="PHI-IND-2026-TNE7WRA", full_name="B")
            )

    asyncio.run(scenario())


def test_hospital_repository_add_and_lookups() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            repo = HospitalRepository(session)
            hosp = await repo.add(
                Hospital(hospital_id="HID-0001", name="Tata Main Hospital", address="Jamshedpur")
            )
            assert hosp.id is not None

            by_id = await repo.get_by_id(hosp.id)
            assert by_id is not None and by_id.hospital_id == "HID-0001"

            by_hid = await repo.get_by_hospital_id("HID-0001")
            assert by_hid is not None and by_hid.id == hosp.id

            all_hosps = await repo.list_all()
            assert len(all_hosps) == 1

            with pytest.raises(DuplicateHospitalIdError):
                await repo.add(Hospital(hospital_id="HID-0001", name="Duplicate"))

    asyncio.run(scenario())


def test_doctor_repository_add_and_lookups() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            user = await UserRepository(session).add(User(firebase_uid="fb-1", role=Role.DOCTOR))
            hosp = await HospitalRepository(session).add(
                Hospital(hospital_id="HID-0001", name="Hospital 1")
            )
            repo = DoctorRepository(session)
            doc = await repo.add(
                Doctor(
                    user_id=user.id,
                    hospital_id=hosp.id,
                    full_name="Dr. Rao",
                    registration_number="REG-101",
                    specialty="Cardiology",
                )
            )
            assert doc.id is not None

            by_user = await repo.get_by_user_id(user.id)
            assert by_user is not None and by_user.id == doc.id

            by_reg = await repo.get_by_registration_number("REG-101")
            assert by_reg is not None and by_reg.id == doc.id

            by_id = await repo.get_by_id(doc.id)
            assert by_id is not None and by_id.id == doc.id

            listed = await repo.list_by_hospital_id(hosp.id)
            assert len(listed) == 1

    asyncio.run(scenario())


def test_doctor_repository_distinguishes_unique_violations() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            users = UserRepository(session)
            u1 = await users.add(User(firebase_uid="fb-1", role=Role.DOCTOR))
            u2 = await users.add(User(firebase_uid="fb-2", role=Role.DOCTOR))
            hosp = await HospitalRepository(session).add(
                Hospital(hospital_id="HID-0001", name="Hospital 1")
            )

            repo = DoctorRepository(session)
            await repo.add(
                Doctor(
                    user_id=u1.id,
                    hospital_id=hosp.id,
                    full_name="Dr. 1",
                    registration_number="REG-1",
                    specialty="Cardiology",
                )
            )

            # Duplicate user_id
            with pytest.raises(DuplicateDoctorError):
                await repo.add(
                    Doctor(
                        user_id=u1.id,
                        hospital_id=hosp.id,
                        full_name="Dr. 1b",
                        registration_number="REG-2",
                        specialty="Neurology",
                    )
                )

            # Duplicate registration_number
            with pytest.raises(DuplicateRegistrationNumberError):
                await repo.add(
                    Doctor(
                        user_id=u2.id,
                        hospital_id=hosp.id,
                        full_name="Dr. 2",
                        registration_number="REG-1",
                        specialty="Pediatrics",
                    )
                )

            # Valid second doctor
            await repo.add(
                Doctor(
                    user_id=u2.id,
                    hospital_id=hosp.id,
                    full_name="Dr. 2",
                    registration_number="REG-2",
                    specialty="Pediatrics",
                )
            )

    asyncio.run(scenario())


def test_record_category_repository_add_and_lookups() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            repo = RecordCategoryRepository(session)
            cat = await repo.add(
                RecordCategory(
                    code="CBC",
                    display_name="Complete Blood Count",
                    description="Blood test",
                )
            )
            assert cat.id is not None

            by_id = await repo.get_by_id(cat.id)
            assert by_id is not None and by_id.code == "CBC"

            by_code = await repo.get_by_code("CBC")
            assert by_code is not None and by_code.id == cat.id

            all_cats = await repo.list_all()
            assert len(all_cats) == 1

            with pytest.raises(DuplicateCategoryCodeError):
                await repo.add(RecordCategory(code="CBC", display_name="Duplicate"))

    asyncio.run(scenario())


def test_medical_record_repository_add_and_lookups() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            u_pat = await UserRepository(session).add(
                User(firebase_uid="fb-pat", role=Role.PATIENT)
            )
            patient = await PatientRepository(session).add(
                Patient(user_id=u_pat.id, health_id="PHI-IND-2026-7K3M99X", full_name="Asha Rao")
            )
            cat = await RecordCategoryRepository(session).add(
                RecordCategory(code="CBC", display_name="CBC")
            )

            repo = MedicalRecordRepository(session)
            record = await repo.add(
                MedicalRecord(
                    patient_id=patient.id,
                    category_id=cat.id,
                    origin=RecordOrigin.PATIENT_LOCKER,
                    title="Blood Test",
                    s3_key="s3://records/rec1.pdf",
                    file_name="rec1.pdf",
                    mime_type="application/pdf",
                    processing_status=ProcessingStatus.UPLOADED,
                    is_hidden=False,
                )
            )
            assert record.id is not None

            by_id = await repo.get_by_id(record.id)
            assert by_id is not None and by_id.title == "Blood Test"

            patient_recs = await repo.list_by_patient_id(patient.id)
            assert len(patient_recs) == 1

            cat_recs = await repo.list_by_category_and_patient(patient.id, cat.id)
            assert len(cat_recs) == 1

            # Update status
            updated = await repo.update_status(record.id, ProcessingStatus.INDEXED)
            assert updated is not None and updated.processing_status is ProcessingStatus.INDEXED

            # Toggle hidden
            hidden = await repo.set_hidden(record.id, True)
            assert hidden is not None and hidden.is_hidden is True

            # Excluded from default listing
            assert len(await repo.list_by_patient_id(patient.id, include_hidden=False)) == 0
            assert len(await repo.list_by_patient_id(patient.id, include_hidden=True)) == 1

    asyncio.run(scenario())


def test_consent_repository_lifecycle() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            # 1. Setup Patient, Hospital, Doctor, Category
            u_pat = await UserRepository(session).add(
                User(firebase_uid="fb-pat", role=Role.PATIENT)
            )
            patient = await PatientRepository(session).add(
                Patient(user_id=u_pat.id, health_id="PHI-IND-2026-7K3M99X", full_name="Asha Rao")
            )
            hosp = await HospitalRepository(session).add(
                Hospital(hospital_id="HID-0001", name="Tata Main Hospital")
            )
            u_doc = await UserRepository(session).add(User(firebase_uid="fb-doc", role=Role.DOCTOR))
            doctor = await DoctorRepository(session).add(
                Doctor(
                    user_id=u_doc.id,
                    hospital_id=hosp.id,
                    full_name="Dr. Sharma",
                    registration_number="REG-101",
                    specialty="Cardiology",
                )
            )
            cat = await RecordCategoryRepository(session).add(
                RecordCategory(code="CBC", display_name="CBC")
            )

            repo = ConsentRepository(session)

            # 2. Create AccessRequest
            now_utc = datetime.now(UTC)
            req = AccessRequest(
                patient_id=patient.id,
                doctor_id=doctor.id,
                hospital_id=hosp.id,
                purpose="Pre-op evaluation",
                status=RequestStatus.PENDING,
                expires_at=now_utc + timedelta(days=7),
            )
            created_req = await repo.create_access_request(req, [cat.id])
            assert created_req.id is not None

            # Lookups
            by_id = await repo.get_access_request(created_req.id)
            assert by_id is not None and by_id.purpose == "Pre-op evaluation"

            cat_ids = await repo.get_request_category_ids(created_req.id)
            assert list(cat_ids) == [cat.id]

            pat_reqs = await repo.list_requests_for_patient(patient.id)
            assert len(pat_reqs) == 1

            doc_reqs = await repo.list_requests_for_doctor(doctor.id)
            assert len(doc_reqs) == 1

            # 3. Add Decision
            dec = ConsentDecision(
                request_id=created_req.id,
                patient_id=patient.id,
                doctor_id=doctor.id,
                category_id=cat.id,
                decision=DecisionType.APPROVED,
                decided_at=now_utc,
            )
            decisions = await repo.add_decisions([dec])
            assert len(decisions) == 1

            pat_decs = await repo.list_decisions_for_patient(patient.id)
            assert len(pat_decs) == 1

            # 4. Add Grant
            grant = ConsentGrant(
                patient_id=patient.id,
                doctor_id=doctor.id,
                category_id=cat.id,
                decision_id=decisions[0].id,
                granted_at=now_utc,
                expires_at=now_utc + timedelta(days=90),
            )
            saved_grant = await repo.add_grant(grant)
            assert saved_grant.id is not None

            active = await repo.get_active_grant(patient.id, doctor.id, cat.id, as_of=now_utc)
            assert active is not None and active.id == saved_grant.id

            pat_grants = await repo.list_active_grants_for_patient(patient.id, as_of=now_utc)
            assert len(pat_grants) == 1

            # 5. Revoke Grant
            revoked = await repo.revoke_grant(patient.id, doctor.id, cat.id, revoked_at=now_utc)
            assert revoked is not None and revoked.revoked_at == now_utc

            # Lookup now returns None
            active_after_revoke = await repo.get_active_grant(
                patient.id, doctor.id, cat.id, as_of=now_utc
            )
            assert active_after_revoke is None

    asyncio.run(scenario())


def test_audit_event_repository_lifecycle() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            u_actor = await UserRepository(session).add(
                User(firebase_uid="fb-actor", role=Role.DOCTOR)
            )
            u_pat = await UserRepository(session).add(
                User(firebase_uid="fb-pat", role=Role.PATIENT)
            )
            patient = await PatientRepository(session).add(
                Patient(user_id=u_pat.id, health_id="PHI-IND-2026-7K3M99X", full_name="Asha Rao")
            )

            repo = AuditEventRepository(session)
            now_utc = datetime.now(UTC)

            event = AuditEvent(
                actor_id=u_actor.id,
                actor_role=Role.DOCTOR,
                action=AuditAction.RECORD_VIEWED,
                patient_id=patient.id,
                target_id=uuid4(),
                target_type="RECORD",
                timestamp=now_utc,
                request_context={"client": "web"},
                canonical_hash="a" * 64,
                anchor_status=AnchorStatus.PENDING,
            )

            persisted = await repo.add(event)
            assert persisted.id is not None

            # Lookups
            by_id = await repo.get_by_id(persisted.id)
            assert by_id is not None and by_id.canonical_hash == "a" * 64

            pat_events = await repo.list_by_patient_id(patient.id)
            assert len(pat_events) == 1

            actor_events = await repo.list_by_actor_id(u_actor.id)
            assert len(actor_events) == 1

            count = await repo.count_by_patient_id(patient.id)
            assert count == 1

            # Update anchor status
            updated = await repo.update_anchor_status(
                id=persisted.id,
                status=AnchorStatus.ANCHORED,
                tx_hash="tx-12345",
                anchored_at=now_utc,
            )
            assert updated is not None
            assert updated.anchor_status is AnchorStatus.ANCHORED
            assert updated.anchor_tx_hash == "tx-12345"

    asyncio.run(scenario())
