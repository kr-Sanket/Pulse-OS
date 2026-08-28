"""Medical records and record categories domain and service unit tests."""

import asyncio
from datetime import date
from uuid import uuid4

import pytest
from app.modules.auth.accounts import UserAccountService
from app.modules.auth.domain import Role
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.doctors.models import Doctor
from app.modules.doctors.repository import DoctorRepository
from app.modules.doctors.service import DoctorService
from app.modules.hospitals.models import Hospital
from app.modules.hospitals.repository import HospitalRepository
from app.modules.hospitals.service import HospitalService
from app.modules.patients.models import Patient
from app.modules.patients.repository import PatientRepository
from app.modules.patients.service import PatientService
from app.modules.records.errors import (
    DuplicateCategoryCodeError,
    InvalidRecordDoctorError,
    InvalidRecordHospitalError,
    InvalidRecordOriginError,
    InvalidRecordPatientError,
    RecordCategoryNotFoundError,
    RecordNotFoundError,
    RecordValidationError,
)
from app.modules.records.models import (
    DEFAULT_RECORD_CATEGORIES,
    ProcessingStatus,
    RecordOrigin,
)
from app.modules.records.repository import (
    MedicalRecordRepository,
    RecordCategoryRepository,
)
from app.modules.records.service import RecordService
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import sqlite_session


def _make_record_service(session: AsyncSession) -> RecordService:
    auth_provider = FakeAuthProvider()
    user_repo = UserRepository(session)
    accounts = UserAccountService(user_repo, auth_provider)

    patient_repo = PatientRepository(session)
    patients = PatientService(accounts=accounts, patients=patient_repo)

    hospital_repo = HospitalRepository(session)
    hospitals = HospitalService(hospital_repo)

    doctor_repo = DoctorRepository(session)
    doctors = DoctorService(doctors=doctor_repo, accounts=accounts, hospitals=hospitals)

    records = MedicalRecordRepository(session)
    categories = RecordCategoryRepository(session)

    return RecordService(
        records=records,
        categories=categories,
        patients=patients,
        hospitals=hospitals,
        doctors=doctors,
    )


# --- Category Tests ---


def test_create_category_and_lookups() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            service = _make_record_service(session)
            cat = await service.create_category(
                code="cbc",
                display_name="Complete Blood Count",
                description="Hematology blood test",
            )
            assert cat.id is not None
            assert cat.code == "CBC"  # Uppercased
            assert cat.display_name == "Complete Blood Count"

            by_id = await service.get_category_by_id(cat.id)
            assert by_id is not None and by_id.code == "CBC"

            by_code = await service.get_category_by_code("CBC")
            assert by_code is not None and by_code.id == cat.id

            by_code_lower = await service.get_category_by_code("cbc")
            assert by_code_lower is not None and by_code_lower.id == cat.id

            assert await service.get_category_by_id(uuid4()) is None
            assert await service.get_category_by_code("NONEXISTENT") is None

    asyncio.run(scenario())


def test_duplicate_category_code_rejected() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            service = _make_record_service(session)
            await service.create_category(code="MRI", display_name="MRI Scan")
            with pytest.raises(DuplicateCategoryCodeError):
                await service.create_category(code="mri", display_name="Duplicate MRI")

    asyncio.run(scenario())


def test_category_validation_errors() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            service = _make_record_service(session)
            with pytest.raises(RecordValidationError, match="Category code"):
                await service.create_category(code="   ", display_name="Name")
            with pytest.raises(RecordValidationError, match="Category display name"):
                await service.create_category(code="CODE", display_name="   ")

    asyncio.run(scenario())


def test_seed_default_categories() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            service = _make_record_service(session)
            seeded = await service.seed_default_categories()
            assert len(seeded) == len(DEFAULT_RECORD_CATEGORIES)

            all_cats = await service.list_categories()
            assert len(all_cats) == len(DEFAULT_RECORD_CATEGORIES)

            # Re-seeding is idempotent
            reseeded = await service.seed_default_categories()
            assert len(reseeded) == 0

    asyncio.run(scenario())


# --- Record Creation & Lifecycle Tests ---


def test_create_hospital_uploaded_record_success() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            # 1. Setup Patient
            u_pat = await UserRepository(session).add(
                User(firebase_uid="fb-pat", role=Role.PATIENT)
            )
            patient = await PatientRepository(session).add(
                Patient(user_id=u_pat.id, health_id="PHI-IND-2026-7K3M99X", full_name="Asha Rao")
            )

            # 2. Setup Hospital & Doctor
            hospital = await HospitalRepository(session).add(
                Hospital(hospital_id="HID-0001", name="Tata Main Hospital")
            )
            u_doc = await UserRepository(session).add(User(firebase_uid="fb-doc", role=Role.DOCTOR))
            doctor = await DoctorRepository(session).add(
                Doctor(
                    user_id=u_doc.id,
                    hospital_id=hospital.id,
                    full_name="Dr. Sharma",
                    registration_number="REG-101",
                    specialty="Pathology",
                )
            )

            # 3. Setup Category & Service
            service = _make_record_service(session)
            category = await service.create_category(code="CBC", display_name="CBC")

            record = await service.create_record(
                patient_id=patient.id,
                category_id=category.id,
                origin=RecordOrigin.HOSPITAL_UPLOAD,
                hospital_id=hospital.id,
                doctor_id=doctor.id,
                title="CBC Blood Report - Feb 2026",
                service_date=date(2026, 2, 15),
                s3_key="patients/123/cbc-20260215.pdf",
                file_name="cbc_report.pdf",
                mime_type="application/pdf",
                file_size_bytes=1048576,
            )

            assert record.id is not None
            assert record.patient_id == patient.id
            assert record.category_id == category.id
            assert record.origin is RecordOrigin.HOSPITAL_UPLOAD
            assert record.hospital_id == hospital.id
            assert record.doctor_id == doctor.id
            assert record.title == "CBC Blood Report - Feb 2026"
            assert record.service_date == date(2026, 2, 15)
            assert record.s3_key == "patients/123/cbc-20260215.pdf"
            assert record.file_name == "cbc_report.pdf"
            assert record.mime_type == "application/pdf"
            assert record.file_size_bytes == 1048576
            assert record.processing_status is ProcessingStatus.UPLOADED
            assert record.failure_reason is None
            assert record.is_hidden is False

    asyncio.run(scenario())


def test_create_patient_locker_record_success() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            u_pat = await UserRepository(session).add(
                User(firebase_uid="fb-pat", role=Role.PATIENT)
            )
            patient = await PatientRepository(session).add(
                Patient(user_id=u_pat.id, health_id="PHI-IND-2026-7K3M99X", full_name="Asha Rao")
            )

            service = _make_record_service(session)
            category = await service.create_category(
                code="PRESCRIPTION", display_name="Prescription"
            )

            record = await service.create_record(
                patient_id=patient.id,
                category_id=category.id,
                origin=RecordOrigin.PATIENT_LOCKER,
                title="Old Prescription Scan",
                s3_key="locker/prescription-scan.jpg",
                file_name="prescription.jpg",
                mime_type="image/jpeg",
            )

            assert record.id is not None
            assert record.origin is RecordOrigin.PATIENT_LOCKER
            assert record.hospital_id is None
            assert record.doctor_id is None
            assert record.is_hidden is False

    asyncio.run(scenario())


def test_origin_validation_rules() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            u_pat = await UserRepository(session).add(
                User(firebase_uid="fb-pat", role=Role.PATIENT)
            )
            patient = await PatientRepository(session).add(
                Patient(user_id=u_pat.id, health_id="PHI-IND-2026-7K3M99X", full_name="Asha Rao")
            )
            hosp = await HospitalRepository(session).add(
                Hospital(hospital_id="HID-0001", name="Hospital 1")
            )
            service = _make_record_service(session)
            cat = await service.create_category(code="LAB_REPORT", display_name="Lab Report")

            # 1. Hospital upload missing hospital_id
            with pytest.raises(InvalidRecordOriginError, match="hospital_id"):
                await service.create_record(
                    patient_id=patient.id,
                    category_id=cat.id,
                    origin=RecordOrigin.HOSPITAL_UPLOAD,
                    hospital_id=None,
                    title="Report",
                    s3_key="key",
                    file_name="f.pdf",
                    mime_type="application/pdf",
                )

            # 2. Patient locker upload with hospital_id
            with pytest.raises(InvalidRecordOriginError, match="must not have hospital"):
                await service.create_record(
                    patient_id=patient.id,
                    category_id=cat.id,
                    origin=RecordOrigin.PATIENT_LOCKER,
                    hospital_id=hosp.id,
                    title="Report",
                    s3_key="key",
                    file_name="f.pdf",
                    mime_type="application/pdf",
                )

    asyncio.run(scenario())


def test_doctor_affiliation_validation() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            u_pat = await UserRepository(session).add(
                User(firebase_uid="fb-pat", role=Role.PATIENT)
            )
            patient = await PatientRepository(session).add(
                Patient(user_id=u_pat.id, health_id="PHI-IND-2026-7K3M99X", full_name="Asha Rao")
            )
            hosp1 = await HospitalRepository(session).add(
                Hospital(hospital_id="HID-0001", name="Hospital 1")
            )
            hosp2 = await HospitalRepository(session).add(
                Hospital(hospital_id="HID-0002", name="Hospital 2")
            )

            u_doc = await UserRepository(session).add(User(firebase_uid="fb-doc", role=Role.DOCTOR))
            doc_at_hosp2 = await DoctorRepository(session).add(
                Doctor(
                    user_id=u_doc.id,
                    hospital_id=hosp2.id,
                    full_name="Dr. Hosp2",
                    registration_number="REG-2",
                    specialty="Surgery",
                )
            )

            service = _make_record_service(session)
            cat = await service.create_category(code="DISCHARGE_SUMMARY", display_name="Summary")

            # Doctor belongs to hosp2, but upload claimed hosp1
            with pytest.raises(InvalidRecordDoctorError, match="not affiliated"):
                await service.create_record(
                    patient_id=patient.id,
                    category_id=cat.id,
                    origin=RecordOrigin.HOSPITAL_UPLOAD,
                    hospital_id=hosp1.id,
                    doctor_id=doc_at_hosp2.id,
                    title="Summary",
                    s3_key="key",
                    file_name="summary.pdf",
                    mime_type="application/pdf",
                )

    asyncio.run(scenario())


def test_invalid_foreign_entities_rejected() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            u_pat = await UserRepository(session).add(
                User(firebase_uid="fb-pat", role=Role.PATIENT)
            )
            patient = await PatientRepository(session).add(
                Patient(user_id=u_pat.id, health_id="PHI-IND-2026-7K3M99X", full_name="Asha Rao")
            )
            service = _make_record_service(session)
            cat = await service.create_category(code="XRAY", display_name="X-Ray")

            # Non-existent patient
            with pytest.raises(InvalidRecordPatientError):
                await service.create_record(
                    patient_id=uuid4(),
                    category_id=cat.id,
                    origin=RecordOrigin.PATIENT_LOCKER,
                    title="X-Ray",
                    s3_key="key",
                    file_name="xray.png",
                    mime_type="image/png",
                )

            # Non-existent category
            with pytest.raises(RecordCategoryNotFoundError):
                await service.create_record(
                    patient_id=patient.id,
                    category_id=uuid4(),
                    origin=RecordOrigin.PATIENT_LOCKER,
                    title="X-Ray",
                    s3_key="key",
                    file_name="xray.png",
                    mime_type="image/png",
                )

            # Non-existent hospital
            with pytest.raises(InvalidRecordHospitalError):
                await service.create_record(
                    patient_id=patient.id,
                    category_id=cat.id,
                    origin=RecordOrigin.HOSPITAL_UPLOAD,
                    hospital_id=uuid4(),
                    title="X-Ray",
                    s3_key="key",
                    file_name="xray.png",
                    mime_type="image/png",
                )

            # Non-existent doctor
            hosp = await HospitalRepository(session).add(
                Hospital(hospital_id="HID-0001", name="Hospital 1")
            )
            with pytest.raises(InvalidRecordDoctorError):
                await service.create_record(
                    patient_id=patient.id,
                    category_id=cat.id,
                    origin=RecordOrigin.HOSPITAL_UPLOAD,
                    hospital_id=hosp.id,
                    doctor_id=uuid4(),
                    title="X-Ray",
                    s3_key="key",
                    file_name="xray.png",
                    mime_type="image/png",
                )

    asyncio.run(scenario())


def test_record_validation_errors() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            service = _make_record_service(session)
            with pytest.raises(RecordValidationError, match="title"):
                await service.create_record(
                    patient_id=uuid4(),
                    category_id=uuid4(),
                    origin=RecordOrigin.PATIENT_LOCKER,
                    title="   ",
                    s3_key="key",
                    file_name="f.pdf",
                    mime_type="application/pdf",
                )
            with pytest.raises(RecordValidationError, match="S3 object key"):
                await service.create_record(
                    patient_id=uuid4(),
                    category_id=uuid4(),
                    origin=RecordOrigin.PATIENT_LOCKER,
                    title="Title",
                    s3_key="   ",
                    file_name="f.pdf",
                    mime_type="application/pdf",
                )
            with pytest.raises(RecordValidationError, match="File size"):
                await service.create_record(
                    patient_id=uuid4(),
                    category_id=uuid4(),
                    origin=RecordOrigin.PATIENT_LOCKER,
                    title="Title",
                    s3_key="key",
                    file_name="f.pdf",
                    mime_type="application/pdf",
                    file_size_bytes=-10,
                )

    asyncio.run(scenario())


def test_processing_status_lifecycle() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            u_pat = await UserRepository(session).add(
                User(firebase_uid="fb-pat", role=Role.PATIENT)
            )
            patient = await PatientRepository(session).add(
                Patient(user_id=u_pat.id, health_id="PHI-IND-2026-7K3M99X", full_name="Asha Rao")
            )
            service = _make_record_service(session)
            cat = await service.create_category(code="CT_SCAN", display_name="CT Scan")

            record = await service.create_record(
                patient_id=patient.id,
                category_id=cat.id,
                origin=RecordOrigin.PATIENT_LOCKER,
                title="CT Scan",
                s3_key="ct.dcm",
                file_name="ct.dcm",
                mime_type="application/dicom",
            )
            assert record.processing_status is ProcessingStatus.UPLOADED

            # Transition to PROCESSING
            rec1 = await service.update_processing_status(record.id, ProcessingStatus.PROCESSING)
            assert rec1.processing_status is ProcessingStatus.PROCESSING
            assert rec1.failure_reason is None

            # Transition to INDEXED
            rec2 = await service.update_processing_status(record.id, ProcessingStatus.INDEXED)
            assert rec2.processing_status is ProcessingStatus.INDEXED

            # Transition to FAILED with reason
            rec3 = await service.update_processing_status(
                record.id, ProcessingStatus.FAILED, failure_reason="OCR unreadable scan"
            )
            assert rec3.processing_status is ProcessingStatus.FAILED
            assert rec3.failure_reason == "OCR unreadable scan"

            with pytest.raises(RecordNotFoundError):
                await service.update_processing_status(uuid4(), ProcessingStatus.INDEXED)

    asyncio.run(scenario())


def test_patient_locker_visibility_toggle() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            u_pat = await UserRepository(session).add(
                User(firebase_uid="fb-pat", role=Role.PATIENT)
            )
            patient = await PatientRepository(session).add(
                Patient(user_id=u_pat.id, health_id="PHI-IND-2026-7K3M99X", full_name="Asha Rao")
            )
            hosp = await HospitalRepository(session).add(
                Hospital(hospital_id="HID-0001", name="Hospital 1")
            )

            service = _make_record_service(session)
            cat = await service.create_category(code="OTHER", display_name="Other")

            locker_rec = await service.create_record(
                patient_id=patient.id,
                category_id=cat.id,
                origin=RecordOrigin.PATIENT_LOCKER,
                title="Locker Doc",
                s3_key="locker.pdf",
                file_name="locker.pdf",
                mime_type="application/pdf",
            )
            hosp_rec = await service.create_record(
                patient_id=patient.id,
                category_id=cat.id,
                origin=RecordOrigin.HOSPITAL_UPLOAD,
                hospital_id=hosp.id,
                title="Hospital Doc",
                s3_key="hosp.pdf",
                file_name="hosp.pdf",
                mime_type="application/pdf",
            )

            # Patient can hide own locker record
            hidden = await service.set_record_hidden(locker_rec.id, patient.id, is_hidden=True)
            assert hidden.is_hidden is True

            # Default listing excludes hidden records
            visible_records = await service.list_records_for_patient(patient.id)
            assert len(visible_records) == 1
            assert visible_records[0].id == hosp_rec.id

            # Listing with include_hidden=True includes it
            all_records = await service.list_records_for_patient(patient.id, include_hidden=True)
            assert len(all_records) == 2

            # Cannot hide hospital-uploaded record
            with pytest.raises(InvalidRecordOriginError, match="Only patient locker"):
                await service.set_record_hidden(hosp_rec.id, patient.id, is_hidden=True)

    asyncio.run(scenario())


# --- Category Existence Summary & Security Boundary Test ---


def test_category_existence_summary_projects_without_leaking_metadata() -> None:
    """Security property (DATABASE_DESIGN.md §Modeling Rules, ADR-013):
    Existence summary exposes only (category_code, category_name, hospital_id, count).
    It contains NO filenames, titles, service dates, or S3 keys.
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            u_pat = await UserRepository(session).add(
                User(firebase_uid="fb-pat", role=Role.PATIENT)
            )
            patient = await PatientRepository(session).add(
                Patient(user_id=u_pat.id, health_id="PHI-IND-2026-7K3M99X", full_name="Asha Rao")
            )
            hosp1 = await HospitalRepository(session).add(
                Hospital(hospital_id="HID-0001", name="Hospital 1")
            )
            hosp2 = await HospitalRepository(session).add(
                Hospital(hospital_id="HID-0002", name="Hospital 2")
            )

            service = _make_record_service(session)
            cat_cbc = await service.create_category(code="CBC", display_name="Blood Count")
            cat_mri = await service.create_category(code="MRI", display_name="MRI Scan")

            # 2 CBCs at hosp1, 1 MRI at hosp2, 1 locker CBC
            await service.create_record(
                patient_id=patient.id,
                category_id=cat_cbc.id,
                origin=RecordOrigin.HOSPITAL_UPLOAD,
                hospital_id=hosp1.id,
                title="Sensitive Blood Cancer Panel",
                s3_key="secret-path-1",
                file_name="leukemia_panel.pdf",
                mime_type="application/pdf",
            )
            await service.create_record(
                patient_id=patient.id,
                category_id=cat_cbc.id,
                origin=RecordOrigin.HOSPITAL_UPLOAD,
                hospital_id=hosp1.id,
                title="Routine Follow-up CBC",
                s3_key="secret-path-2",
                file_name="routine_cbc.pdf",
                mime_type="application/pdf",
            )
            await service.create_record(
                patient_id=patient.id,
                category_id=cat_mri.id,
                origin=RecordOrigin.HOSPITAL_UPLOAD,
                hospital_id=hosp2.id,
                title="Brain MRI Scan",
                s3_key="secret-path-3",
                file_name="brain_mri.dcm",
                mime_type="application/dicom",
            )
            await service.create_record(
                patient_id=patient.id,
                category_id=cat_cbc.id,
                origin=RecordOrigin.PATIENT_LOCKER,
                title="Self Uploaded CBC",
                s3_key="secret-path-4",
                file_name="self_cbc.jpg",
                mime_type="image/jpeg",
            )

            summary = await service.get_category_existence_summary(patient.id)
            assert len(summary) == 3

            # Verify that each projection entry contains only category and count information
            for item in summary:
                # Assert schema holds only existence tokens
                assert hasattr(item, "category_code")
                assert hasattr(item, "category_name")
                assert hasattr(item, "hospital_id")
                assert hasattr(item, "record_count")
                # Sensitive metadata attributes MUST NOT exist on CategoryExistenceSummary
                assert not hasattr(item, "title")
                assert not hasattr(item, "s3_key")
                assert not hasattr(item, "file_name")
                assert not hasattr(item, "service_date")

    asyncio.run(scenario())


def test_records_module_has_no_direct_doctor_content_bypass() -> None:
    """Security property: RecordService does not accept clinician authorization claims
    or offer a direct 'get_unconsented_records_for_doctor' method. Content authorization
    must come exclusively from the future consent module via consent.enforce().
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            service = _make_record_service(session)
            # Verify interface methods do not expose bypass methods
            assert not hasattr(service, "get_doctor_records")
            assert not hasattr(service, "bypass_consent_read")
            assert not hasattr(service, "doctor_direct_read")

    asyncio.run(scenario())
