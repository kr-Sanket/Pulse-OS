"""Real ConsentService + real AI retrieval: the clinician search writes the audit trail.

The search endpoint returns record text, so it must leave the same kind of trace as the
granted-records listing it mirrors — one scope-level event per request — but under its own
action: RECORDS_SEARCHED when a scope was searched (never RECORDS_LISTED, which names a
chooser, not record text) and ACCESS_DENIED when there was none. It must never put the query
or any record text on the trail.
"""

import asyncio
from datetime import date
from uuid import uuid4

from app.modules.ai.query import AIQueryService
from app.modules.ai.repository import AIRepository
from app.modules.ai.service import AIIngestionService, AIRetrievalService
from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.auth.models import User
from app.modules.consent.dependencies import RecordsStaffDirectory
from app.modules.consent.models import AuditAction, AuditLog
from app.modules.consent.repository import (
    AuditLogRepository,
    ConsentDecisionRepository,
    ConsentGrantRepository,
    ConsentRequestCategoryRepository,
    ConsentRequestRepository,
)
from app.modules.consent.service import ConsentService
from app.modules.patients.directory import PatientDirectoryService
from app.modules.patients.models import Patient
from app.modules.patients.repository import PatientRepository
from app.modules.records.directory import staff_directory
from app.modules.records.models import (
    Doctor,
    DoctorStatus,
    Hospital,
    HospitalVerificationStatus,
    MedicalRecord,
    RecordCategory,
    RecordOrigin,
)
from sqlalchemy import select
from tests.support import FakeClinicianDirectory, sqlite_session

SECRET_QUERY = "metformin"
RECORD_TEXT = "metformin diabetes daily oral medication"


def test_clinician_search_is_audited_as_denied_then_listed_and_never_stores_the_query() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            patient_user = User(firebase_uid=f"fb-p-{uuid4()}", role=Role.PATIENT)
            doctor_user = User(firebase_uid=f"fb-d-{uuid4()}", role=Role.DOCTOR)
            session.add_all([patient_user, doctor_user])
            hospital = Hospital(
                hid="HID-0091", name="TMH", verification_status=HospitalVerificationStatus.VERIFIED
            )
            session.add(hospital)
            await session.flush()
            patient = Patient(
                user_id=patient_user.id, health_id="PHI-IND-2026-1QE8DVR", full_name="Aarav"
            )
            doctor = Doctor(
                user_id=doctor_user.id,
                hospital_id=hospital.id,
                full_name="Dr Verma",
                registration_number="R-91",
                status=DoctorStatus.ACTIVE,
            )
            category = RecordCategory(code="PRESCRIPTION", display_name="Prescription")
            session.add_all([patient, doctor, category])
            await session.flush()
            record = MedicalRecord(
                patient_id=patient.id,
                category_id=category.id,
                origin=RecordOrigin.HOSPITAL_UPLOAD,
                uploaded_by_hospital_id=hospital.id,
                date_of_service=date(2026, 3, 2),
                original_filename="rx.json",
                content_type="application/fhir+json",
                size_bytes=10,
                s3_key=f"records/{patient.id}/rx",
            )
            session.add(record)
            await session.flush()

            ai_repository = AIRepository(session)
            await AIIngestionService(ai_repository).index_record(
                record_id=record.id,
                patient_id=patient.id,
                category_id=category.id,
                normalized_text=RECORD_TEXT,
                max_tokens=20,
            )

            clinicians = FakeClinicianDirectory()
            clinicians.register(doctor_user.id, doctor_id=doctor.id, hospital_id=hospital.id)
            patients = PatientDirectoryService(PatientRepository(session))
            consent = ConsentService(
                requests=ConsentRequestRepository(session),
                request_categories=ConsentRequestCategoryRepository(session),
                decisions=ConsentDecisionRepository(session),
                grants=ConsentGrantRepository(session),
                audit=AuditLogRepository(session),
                patients=patients,
                clinicians=clinicians,
                staff=RecordsStaffDirectory(staff_directory(session)),
            )
            service = AIQueryService(
                retrieval=AIRetrievalService(ai_repository),
                consent=consent,
                auditor=consent,
                search_auditor=consent,
                patients=patients,
            )
            doctor_auth = AuthenticatedUser(
                user_id=doctor_user.id, firebase_uid=doctor_user.firebase_uid, role=Role.DOCTOR
            )
            patient_auth = AuthenticatedUser(
                user_id=patient_user.id, firebase_uid=patient_user.firebase_uid, role=Role.PATIENT
            )

            async def trail() -> list[AuditLog]:
                result = await session.execute(
                    select(AuditLog).where(AuditLog.patient_id == patient.id)
                )
                return list(result.scalars())

            # 1. No grant: nothing returned, and the attempt is on the patient's trail.
            assert (
                await service.search_records(
                    doctor_auth, patient_id=patient.id, query=SECRET_QUERY, request_context="r1"
                )
                == []
            )
            denied = [row for row in await trail() if row.action is AuditAction.ACCESS_DENIED]
            assert len(denied) == 1
            assert denied[0].actor_user_id == doctor_user.id
            assert denied[0].actor_hospital_id == hospital.id

            # 2. An id naming no patient: nothing returned, nothing written anywhere.
            before = len((await session.execute(select(AuditLog))).scalars().all())
            assert await service.search_records(doctor_auth, patient_id=uuid4(), query="x") == []
            assert len((await session.execute(select(AuditLog))).scalars().all()) == before

            # 3. With a grant: the record text comes back and one RECORDS_SEARCHED is written.
            view = await consent.create_request(
                doctor_auth,
                patient_health_id=patient.health_id,
                category_ids=[category.id],
                purpose="review",
            )
            await consent.approve_categories(patient_auth, view.request.id, [category.id])
            found = await service.search_records(
                doctor_auth, patient_id=patient.id, query=SECRET_QUERY, request_context="r3"
            )
            assert found and all(chunk.record_id == record.id for chunk in found)
            searched = [row for row in await trail() if row.action is AuditAction.RECORDS_SEARCHED]
            assert len(searched) == 1
            assert searched[0].request_context == "r3"
            assert searched[0].actor_hospital_id == hospital.id
            # Scope-level, like a listing: no target column is set.
            assert searched[0].target_record_id is None
            assert searched[0].target_category_id is None
            assert searched[0].target_request_id is None
            # The search is not recorded as a listing.
            assert not [r for r in await trail() if r.action is AuditAction.RECORDS_LISTED]

            # 4. A search that matches nothing in the granted scope is still a search.
            assert (
                await service.search_records(
                    doctor_auth, patient_id=patient.id, query="zzzz-no-match", request_context="r4"
                )
                == []
            )
            searched = [row for row in await trail() if row.action is AuditAction.RECORDS_SEARCHED]
            assert [row.request_context for row in searched].count("r4") == 1

            # Neither the query nor any record text reaches any audit column.
            for row in await trail():
                stored = " ".join(str(value) for value in vars(row).values())
                assert SECRET_QUERY not in stored
                assert RECORD_TEXT not in stored

    asyncio.run(scenario())
