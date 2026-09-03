"""RecordService unit tests: uploads, relationship-scoped reads, presigned downloads.

The M2 access invariants live here: a patient sees only their own records, a hospital
admin only their hospital's uploads, and nothing else exists (doctor access is M3).
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

import pytest
from app.core.queue import InMemoryJobQueue, QueueUnavailableError
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
from app.modules.records.errors import (
    EmptyFileError,
    FileTooLargeError,
    HospitalNotVerifiedError,
    ProfileNotFoundError,
    RecordNotFoundError,
    StorageUnavailableError,
    UnknownCategoryError,
    UnknownPatientError,
    UnsupportedFileTypeError,
)
from app.modules.records.fake import FakeObjectStorage
from app.modules.records.models import (
    Hospital,
    HospitalAdmin,
    HospitalVerificationStatus,
    RecordOrigin,
    RecordProcessingStatus,
)
from app.modules.records.repository import (
    HospitalAdminRepository,
    HospitalRepository,
    MedicalRecordRepository,
    RecordCategoryRepository,
)
from app.modules.records.seed import seed_reference_data
from app.modules.records.service import RECORD_UPLOADED_TASK, FileUpload, RecordService
from app.shared.pagination import CursorKey, decode_cursor
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import FakeClinicianDirectory, sqlite_session

PDF = FileUpload(filename="cbc report.pdf", content_type="application/pdf", data=b"%PDF-1.7 x")


@dataclass
class Harness:
    service: RecordService
    consent: ConsentService
    audit: AuditLogRepository
    storage: FakeObjectStorage
    queue: InMemoryJobQueue
    admin_caller: AuthenticatedUser
    patient_caller: AuthenticatedUser
    doctor_caller: AuthenticatedUser
    patient: Patient
    hospital: Hospital


async def _harness(
    session: AsyncSession,
    *,
    verified: bool = True,
    max_upload_bytes: int = 1024,
) -> Harness:
    await seed_reference_data(session)

    hospital = Hospital(
        hid="HID-7001",
        name="Test Hospital",
        verification_status=(
            HospitalVerificationStatus.VERIFIED if verified else HospitalVerificationStatus.PENDING
        ),
    )
    session.add(hospital)
    admin_user = User(firebase_uid=f"fb-admin-{uuid4()}", role=Role.HOSPITAL_ADMIN)
    patient_user = User(firebase_uid=f"fb-patient-{uuid4()}", role=Role.PATIENT)
    doctor_user = User(firebase_uid=f"fb-doctor-{uuid4()}", role=Role.DOCTOR)
    session.add_all([admin_user, patient_user, doctor_user])
    await session.flush()
    session.add(HospitalAdmin(user_id=admin_user.id, hospital_id=hospital.id, full_name="Admin"))
    patient = Patient(
        user_id=patient_user.id, health_id="PHI-IND-2026-1QE8DVR", full_name="Aarav (Demo)"
    )
    session.add(patient)
    await session.flush()

    storage = FakeObjectStorage()
    queue = InMemoryJobQueue()
    consent = ConsentService(
        requests=ConsentRequestRepository(session),
        request_categories=ConsentRequestCategoryRepository(session),
        decisions=ConsentDecisionRepository(session),
        grants=ConsentGrantRepository(session),
        audit=AuditLogRepository(session),
        patients=PatientDirectoryService(PatientRepository(session)),
        clinicians=FakeClinicianDirectory(),
        staff=RecordsStaffDirectory(staff_directory(session)),
    )
    service = RecordService(
        records=MedicalRecordRepository(session),
        categories=RecordCategoryRepository(session),
        admins=HospitalAdminRepository(session),
        hospitals=HospitalRepository(session),
        patients=PatientDirectoryService(PatientRepository(session)),
        storage=storage,
        queue=queue,
        consent=consent,
        presign_ttl_seconds=300,
        max_upload_bytes=max_upload_bytes,
    )
    return Harness(
        service=service,
        consent=consent,
        audit=AuditLogRepository(session),
        storage=storage,
        queue=queue,
        admin_caller=AuthenticatedUser(
            user_id=admin_user.id, firebase_uid=admin_user.firebase_uid, role=Role.HOSPITAL_ADMIN
        ),
        patient_caller=AuthenticatedUser(
            user_id=patient_user.id, firebase_uid=patient_user.firebase_uid, role=Role.PATIENT
        ),
        doctor_caller=AuthenticatedUser(
            user_id=doctor_user.id, firebase_uid=doctor_user.firebase_uid, role=Role.DOCTOR
        ),
        patient=patient,
        hospital=hospital,
    )


def test_hospital_upload_stores_metadata_file_and_job() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            view = await h.service.upload_for_health_id(
                h.admin_caller,
                patient_health_id="  phi-ind-2026-1qe8dvr ",  # desk-typed input tolerated
                category_code="cbc",
                date_of_service=date(2026, 3, 1),
                description="Routine CBC",
                file=PDF,
            )
            record = view.record
            assert record.patient_id == h.patient.id
            assert record.origin is RecordOrigin.HOSPITAL_UPLOAD
            assert record.uploaded_by_hospital_id == h.hospital.id
            assert record.processing_status is RecordProcessingStatus.UPLOADED
            assert record.size_bytes == len(PDF.data)
            assert record.s3_key == f"records/{h.patient.id}/{record.id}"
            assert view.category.code == "CBC"
            assert view.hospital is h.hospital

            stored = h.storage.objects[record.s3_key]
            assert stored.data == PDF.data and stored.content_type == "application/pdf"
            assert h.queue.jobs == [(RECORD_UPLOADED_TASK, {"record_id": str(record.id)})]

    asyncio.run(scenario())


def test_locker_upload_has_no_hospital_provenance() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            view = await h.service.upload_to_own_locker(
                h.patient_caller,
                category_code="PRESCRIPTION",
                date_of_service=date(2026, 1, 15),
                description=None,
                file=PDF,
            )
            assert view.record.origin is RecordOrigin.PATIENT_LOCKER
            assert view.record.uploaded_by_hospital_id is None
            assert view.hospital is None

    asyncio.run(scenario())


def test_upload_validation_failures() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session, max_upload_bytes=64)

            async def attempt(file: FileUpload) -> None:
                await h.service.upload_for_health_id(
                    h.admin_caller,
                    patient_health_id="PHI-IND-2026-1QE8DVR",
                    category_code="CBC",
                    date_of_service=date(2026, 3, 1),
                    description=None,
                    file=file,
                )

            with pytest.raises(UnsupportedFileTypeError):
                await attempt(
                    FileUpload(filename="x.exe", content_type="application/zip", data=b"x")
                )
            with pytest.raises(EmptyFileError):
                await attempt(
                    FileUpload(filename="x.pdf", content_type="application/pdf", data=b"")
                )
            with pytest.raises(FileTooLargeError):
                await attempt(
                    FileUpload(filename="x.pdf", content_type="application/pdf", data=b"x" * 65)
                )
            with pytest.raises(UnknownPatientError):
                await h.service.upload_for_health_id(
                    h.admin_caller,
                    patient_health_id="PHI-IND-2026-XXXXXXX",
                    category_code="CBC",
                    date_of_service=date(2026, 3, 1),
                    description=None,
                    file=PDF,
                )
            with pytest.raises(UnknownCategoryError):
                await h.service.upload_for_health_id(
                    h.admin_caller,
                    patient_health_id="PHI-IND-2026-1QE8DVR",
                    category_code="NOT_A_CATEGORY",
                    date_of_service=date(2026, 3, 1),
                    description=None,
                    file=PDF,
                )
            assert h.storage.objects == {} and h.queue.jobs == []

    asyncio.run(scenario())


def test_upload_requires_a_verified_hospital_and_a_profile_row() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session, verified=False)
            with pytest.raises(HospitalNotVerifiedError):
                await h.service.upload_for_health_id(
                    h.admin_caller,
                    patient_health_id="PHI-IND-2026-1QE8DVR",
                    category_code="CBC",
                    date_of_service=date(2026, 3, 1),
                    description=None,
                    file=PDF,
                )
            ghost_admin = AuthenticatedUser(
                user_id=uuid4(), firebase_uid="fb-ghost", role=Role.HOSPITAL_ADMIN
            )
            with pytest.raises(ProfileNotFoundError):
                await h.service.upload_for_health_id(
                    ghost_admin,
                    patient_health_id="PHI-IND-2026-1QE8DVR",
                    category_code="CBC",
                    date_of_service=date(2026, 3, 1),
                    description=None,
                    file=PDF,
                )

    asyncio.run(scenario())


def test_storage_failure_propagates_before_any_job_is_queued() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            h.storage.storage_error = StorageUnavailableError()
            with pytest.raises(StorageUnavailableError):
                await h.service.upload_to_own_locker(
                    h.patient_caller,
                    category_code="CBC",
                    date_of_service=date(2026, 3, 1),
                    description=None,
                    file=PDF,
                )
            assert h.queue.jobs == []  # never announce a file that was not stored

    asyncio.run(scenario())


def test_queue_failure_never_fails_the_upload(caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            h.queue.enqueue_error = QueueUnavailableError()
            with caplog.at_level(logging.WARNING, logger="app.modules.records.service"):
                view = await h.service.upload_to_own_locker(
                    h.patient_caller,
                    category_code="CBC",
                    date_of_service=date(2026, 3, 1),
                    description=None,
                    file=PDF,
                )
            assert view.record.s3_key in h.storage.objects  # upload succeeded (ADR-014)
            assert any("enqueue failed" in r.message for r in caplog.records)
            # No PHI in the degradation log — the opaque record id only.
            assert all("cbc report.pdf" not in r.getMessage() for r in caplog.records)

    asyncio.run(scenario())


def test_listing_is_scoped_per_caller_and_filterable() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            hospital_view = await h.service.upload_for_health_id(
                h.admin_caller,
                patient_health_id="PHI-IND-2026-1QE8DVR",
                category_code="CBC",
                date_of_service=date(2026, 3, 1),
                description=None,
                file=PDF,
            )
            locker_view = await h.service.upload_to_own_locker(
                h.patient_caller,
                category_code="MRI",
                date_of_service=date(2026, 3, 2),
                description=None,
                file=PDF,
            )

            patient_page = await h.service.list_for_caller(
                h.patient_caller, category_code=None, after=None, limit=10
            )
            assert {v.record.id for v in patient_page.items} == {
                hospital_view.record.id,
                locker_view.record.id,
            }

            admin_page = await h.service.list_for_caller(
                h.admin_caller, category_code=None, after=None, limit=10
            )
            # The locker record is invisible to the hospital: it did not upload it.
            assert [v.record.id for v in admin_page.items] == [hospital_view.record.id]

            only_mri = await h.service.list_for_caller(
                h.patient_caller, category_code="MRI", after=None, limit=10
            )
            assert [v.record.id for v in only_mri.items] == [locker_view.record.id]

    asyncio.run(scenario())


def test_reads_outside_the_relationship_scope_are_404() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            locker_view = await h.service.upload_to_own_locker(
                h.patient_caller,
                category_code="CBC",
                date_of_service=date(2026, 3, 1),
                description=None,
                file=PDF,
            )
            # The admin's hospital did not upload this record → invisible.
            with pytest.raises(RecordNotFoundError):
                await h.service.get_for_caller(h.admin_caller, locker_view.record.id)
            with pytest.raises(RecordNotFoundError):
                await h.service.create_download_link(h.admin_caller, locker_view.record.id)
            with pytest.raises(RecordNotFoundError):
                await h.service.get_for_caller(h.patient_caller, uuid4())

            # A clinician without a grant is refused, and cannot tell refusal from absence.
            with pytest.raises(RecordNotFoundError):
                await h.service.get_for_caller(h.doctor_caller, locker_view.record.id)
            # ...and the refusal is on the record, not silent: consent audited it.
            trail = await h.audit.list_page_by_patient(h.patient.id, after=None, limit=10)
            assert [row.action.value for row in trail] == ["ACCESS_DENIED"]
            assert trail[0].target_record_id == locker_view.record.id

    asyncio.run(scenario())


def test_download_link_carries_the_configured_ttl() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            view = await h.service.upload_to_own_locker(
                h.patient_caller,
                category_code="CBC",
                date_of_service=date(2026, 3, 1),
                description=None,
                file=PDF,
            )
            link = await h.service.create_download_link(h.patient_caller, view.record.id)
            assert link.expires_in_seconds == 300
            assert view.record.s3_key in link.url

    asyncio.run(scenario())


def test_pagination_walks_all_records_without_overlap() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            created: set[UUID] = set()
            for index in range(5):
                view = await h.service.upload_to_own_locker(
                    h.patient_caller,
                    category_code="CBC",
                    date_of_service=date(2026, 3, 1),
                    description=f"upload {index}",
                    file=PDF,
                )
                created.add(view.record.id)

            seen: set[UUID] = set()
            after: CursorKey | None = None
            pages = 0
            while True:
                page = await h.service.list_for_caller(
                    h.patient_caller, category_code=None, after=after, limit=2
                )
                seen.update(v.record.id for v in page.items)
                pages += 1
                if page.next_cursor is None:
                    break
                after = decode_cursor(page.next_cursor)
            assert seen == created
            assert pages == 3  # 2 + 2 + 1

    asyncio.run(scenario())
