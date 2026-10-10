"""High-fidelity integration test: real ConsentService controls real AI retrieval pipeline."""

import asyncio
from datetime import date
from uuid import uuid4

from app.modules.ai.query import AIQueryService
from app.modules.ai.repository import AIRepository
from app.modules.ai.service import AIIngestionService, AIRetrievalService
from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.auth.models import User
from app.modules.consent.dependencies import RecordsStaffDirectory
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
from tests.support import FakeClinicianDirectory, sqlite_session


def test_consent_scoped_ai_retrieval_lifecycle():
    """Verify end-to-end that real ConsentService strictly gates AI retrieval."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            # 1. Patient
            patient_user = User(
                firebase_uid=f"fb-patient-{uuid4()}",
                role=Role.PATIENT,
            )
            session.add(patient_user)
            await session.flush()

            patient = Patient(
                user_id=patient_user.id,
                health_id=f"PHI-IND-2026-{str(uuid4())[:7].upper()}",
                full_name="Consent Scoped Test Patient",
            )
            session.add(patient)
            await session.flush()

            # 2. Hospital
            hospital = Hospital(
                hid=f"HID-{str(uuid4())[:4].upper()}",
                name="Test General Hospital",
                verification_status=HospitalVerificationStatus.VERIFIED,
            )
            session.add(hospital)
            await session.flush()

            # 3. Active Doctor
            doctor_user = User(
                firebase_uid=f"fb-doctor-{uuid4()}",
                role=Role.DOCTOR,
            )
            session.add(doctor_user)
            await session.flush()

            doctor = Doctor(
                user_id=doctor_user.id,
                hospital_id=hospital.id,
                full_name="Dr Clinician",
                registration_number=f"REG-{str(uuid4())[:6].upper()}",
                status=DoctorStatus.ACTIVE,
            )
            session.add(doctor)
            await session.flush()

            # 4. Clinician Directory registration
            clinicians = FakeClinicianDirectory()
            clinicians.register(
                doctor_user.id,
                doctor_id=doctor.id,
                hospital_id=hospital.id,
                is_active=True,
            )

            # 5. Two Record Categories
            cat_lab = RecordCategory(
                code="LAB_REPORT",
                display_name="Lab Report",
            )
            cat_rx = RecordCategory(
                code="PRESCRIPTION",
                display_name="Prescription",
            )
            session.add_all([cat_lab, cat_rx])
            await session.flush()

            # 6. Two Medical Records for the same patient
            lab_record = MedicalRecord(
                id=uuid4(),
                patient_id=patient.id,
                category_id=cat_lab.id,
                origin=RecordOrigin.HOSPITAL_UPLOAD,
                uploaded_by_hospital_id=hospital.id,
                uploaded_by_doctor_id=doctor.id,
                date_of_service=date(2026, 3, 1),
                description="Fasting blood work report",
                original_filename="lab_report.json",
                content_type="application/fhir+json",
                size_bytes=100,
                s3_key=f"records/{patient.id}/lab-1",
            )
            rx_record = MedicalRecord(
                id=uuid4(),
                patient_id=patient.id,
                category_id=cat_rx.id,
                origin=RecordOrigin.HOSPITAL_UPLOAD,
                uploaded_by_hospital_id=hospital.id,
                uploaded_by_doctor_id=doctor.id,
                date_of_service=date(2026, 3, 2),
                description="Prescription order",
                original_filename="prescription.json",
                content_type="application/fhir+json",
                size_bytes=100,
                s3_key=f"records/{patient.id}/rx-1",
            )
            session.add_all([lab_record, rx_record])
            await session.flush()

            # 7. Index both records using real AIIngestionService
            # Both contain "diabetes", but in different clinical categories
            ai_repository = AIRepository(session)
            ingestion_service = AIIngestionService(ai_repository)

            lab_doc = await ingestion_service.index_record(
                record_id=lab_record.id,
                patient_id=patient.id,
                category_id=cat_lab.id,
                normalized_text="glucose test diabetes fasting report",
                max_tokens=20,
            )
            rx_doc = await ingestion_service.index_record(
                record_id=rx_record.id,
                patient_id=patient.id,
                category_id=cat_rx.id,
                normalized_text="metformin diabetes daily oral medication",
                max_tokens=20,
            )
            assert lab_doc is not None
            assert rx_doc is not None

            # Verify both chunks are physically persisted in SQLite before consent evaluation
            indexed_chunks = await ai_repository.search_chunks(
                patient_id=patient.id,
                category_ids=frozenset({cat_lab.id, cat_rx.id}),
            )
            assert len(indexed_chunks) == 2
            assert any(
                "diabetes" in c.content and c.category_id == cat_lab.id
                for c in indexed_chunks
            )
            assert any(
                "diabetes" in c.content and c.category_id == cat_rx.id
                for c in indexed_chunks
            )

            # Build real services wired together
            consent_service = ConsentService(
                requests=ConsentRequestRepository(session),
                request_categories=ConsentRequestCategoryRepository(session),
                decisions=ConsentDecisionRepository(session),
                grants=ConsentGrantRepository(session),
                audit=AuditLogRepository(session),
                patients=PatientDirectoryService(PatientRepository(session)),
                clinicians=clinicians,
                staff=RecordsStaffDirectory(staff_directory(session)),
            )
            retrieval_service = AIRetrievalService(ai_repository)
            query_service = AIQueryService(
                retrieval=retrieval_service,
                consent=consent_service,
            )

            doctor_auth = AuthenticatedUser(
                user_id=doctor_user.id,
                firebase_uid=doctor_user.firebase_uid,
                role=Role.DOCTOR,
            )
            patient_auth = AuthenticatedUser(
                user_id=patient_user.id,
                firebase_uid=patient_user.firebase_uid,
                role=Role.PATIENT,
            )

            # -------------------------------------------------------------
            # PHASE 1 — ZERO CONSENT
            # DOCTOR role alone must yield zero retrieval results.
            # -------------------------------------------------------------
            phase1_results = await query_service.search(
                doctor_auth,
                patient_id=patient.id,
                query="diabetes",
            )
            assert phase1_results == []

            # -------------------------------------------------------------
            # PHASE 2 — CATEGORY-SCOPED CONSENT
            # Doctor requests LAB_REPORT only; Patient approves LAB_REPORT.
            # -------------------------------------------------------------
            request_view = await consent_service.create_request(
                doctor_auth,
                patient_health_id=patient.health_id,
                category_ids=[cat_lab.id],
                purpose="diagnostic consultation",
            )
            decision_outcome = await consent_service.approve_categories(
                patient_auth,
                request_view.request.id,
                [cat_lab.id],
            )
            assert len(decision_outcome.grants) == 1
            grant = decision_outcome.grants[0]
            assert grant.category_id == cat_lab.id

            phase2_results = await query_service.search(
                doctor_auth,
                patient_id=patient.id,
                query="diabetes",
            )

            # Assert retrieval found results strictly bounded to LAB_REPORT
            assert len(phase2_results) > 0
            assert all(chunk.category_id == cat_lab.id for chunk in phase2_results)
            assert all(chunk.record_id == lab_record.id for chunk in phase2_results)
            assert all(chunk.category_id != cat_rx.id for chunk in phase2_results)
            assert any("glucose" in chunk.content for chunk in phase2_results)

            # -------------------------------------------------------------
            # TEMPORAL QUERY UNDER CONSENT SCOPE (T6: Consent Invariance)
            # Even if rx_record is NEWER (2026-03-02 vs 2026-03-01), the unconsented
            # PRESCRIPTION category must remain strictly excluded.
            # -------------------------------------------------------------
            temporal_results = await query_service.search(
                doctor_auth,
                patient_id=patient.id,
                query="What are the patient's latest diabetes findings?",
            )
            assert len(temporal_results) > 0
            assert all(chunk.category_id == cat_lab.id for chunk in temporal_results)
            assert all(chunk.record_id == lab_record.id for chunk in temporal_results)
            assert all(chunk.category_id != cat_rx.id for chunk in temporal_results)
            assert temporal_results[0].date_of_service == date(2026, 3, 1)

            # -------------------------------------------------------------
            # PATIENT ISOLATION UNDER TEMPORAL QUERY (T7: Patient Isolation)
            # Querying patient 1 must never return records from another patient,
            # even if that other patient has a newer record matching the query.
            # -------------------------------------------------------------
            other_patient_user = User(
                firebase_uid=f"fb-patient-other-{uuid4()}",
                role=Role.PATIENT,
            )
            session.add(other_patient_user)
            await session.flush()

            other_patient = Patient(
                user_id=other_patient_user.id,
                health_id=f"PHI-IND-2026-{str(uuid4())[:7].upper()}",
                full_name="Other Test Patient",
            )
            session.add(other_patient)
            await session.flush()

            other_lab_record = MedicalRecord(
                id=uuid4(),
                patient_id=other_patient.id,
                category_id=cat_lab.id,
                origin=RecordOrigin.HOSPITAL_UPLOAD,
                uploaded_by_hospital_id=hospital.id,
                uploaded_by_doctor_id=doctor.id,
                date_of_service=date(2026, 3, 15),  # Newer than patient 1
                description="Newer lab report for other patient",
                original_filename="other_lab.json",
                content_type="application/fhir+json",
                size_bytes=100,
                s3_key=f"records/{other_patient.id}/lab-newer",
            )
            session.add(other_lab_record)
            await session.flush()

            await ingestion_service.index_record(
                record_id=other_lab_record.id,
                patient_id=other_patient.id,
                category_id=cat_lab.id,
                normalized_text="glucose test diabetes fasting report",
                max_tokens=20,
            )

            # Query for patient 1: must never return other_patient's record
            p1_results = await query_service.search(
                doctor_auth,
                patient_id=patient.id,
                query="latest diabetes findings",
            )
            assert all(chunk.patient_id == patient.id for chunk in p1_results)
            assert all(chunk.record_id != other_lab_record.id for chunk in p1_results)

            # -------------------------------------------------------------
            # PHASE 3 — REVOCATION
            # Patient revokes the grant; retrieval must immediately close.
            # -------------------------------------------------------------
            revoked_grant = await consent_service.revoke_grant(patient_auth, grant.id)
            assert revoked_grant.revoked_at is not None

            phase3_results = await query_service.search(
                doctor_auth,
                patient_id=patient.id,
                query="diabetes",
            )
            assert phase3_results == []

    asyncio.run(scenario())
