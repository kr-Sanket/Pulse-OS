"""RecordService unit tests: uploads, relationship-scoped reads, presigned downloads.

The M2 access invariants live here: a patient sees only their own records, a hospital
admin only their hospital's uploads, and nothing else exists (doctor access is M3).
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.core.queue import InMemoryJobQueue, QueueUnavailableError
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
from app.modules.consent.service import ConsentService, as_utc
from app.modules.patients.directory import PatientDirectoryService
from app.modules.patients.models import Patient
from app.modules.patients.repository import PatientRepository
from app.modules.records.directory import staff_directory
from app.modules.records.errors import (
    ClinicianNotActiveError,
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
    Doctor,
    DoctorStatus,
    Hospital,
    HospitalAdmin,
    HospitalVerificationStatus,
    RecordOrigin,
    RecordProcessingStatus,
)
from app.modules.records.repository import (
    DoctorRepository,
    HospitalAdminRepository,
    HospitalRepository,
    MedicalRecordRepository,
    RecordCategoryRepository,
)
from app.modules.records.seed import seed_reference_data
from app.modules.records.service import (
    RECORD_UPLOADED_TASK,
    FileUpload,
    RecordService,
    RecordView,
)
from app.shared.pagination import DateCursor, decode_date_cursor
from app.shared.time import utc_now
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import (
    FakeClinicianDirectory,
    counting_statements,
    sqlite_session,
    sqlite_session_with_engine,
)

PDF = FileUpload(filename="cbc report.pdf", content_type="application/pdf", data=b"%PDF-1.7 x")


@dataclass
class Harness:
    service: RecordService
    consent: ConsentService
    audit: AuditLogRepository
    categories: RecordCategoryRepository
    storage: FakeObjectStorage
    queue: InMemoryJobQueue
    admin_caller: AuthenticatedUser
    patient_caller: AuthenticatedUser
    doctor_caller: AuthenticatedUser
    patient: Patient
    hospital: Hospital
    doctor: Doctor


async def _harness(
    session: AsyncSession,
    *,
    verified: bool = True,
    max_upload_bytes: int = 1024,
    clock: Callable[[], datetime] = utc_now,
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
    doctor = Doctor(
        user_id=doctor_user.id,
        hospital_id=hospital.id,
        full_name="Dr Verma",
        registration_number="REG-1",
        status=DoctorStatus.ACTIVE,
    )
    session.add(doctor)
    patient = Patient(
        user_id=patient_user.id, health_id="PHI-IND-2026-1QE8DVR", full_name="Aarav (Demo)"
    )
    session.add(patient)
    await session.flush()

    storage = FakeObjectStorage()
    queue = InMemoryJobQueue()
    # ``records`` owns the Doctor row; consent reaches it through the directory protocol,
    # so a clinician the grant path must recognise has to be registered here too.
    clinicians = FakeClinicianDirectory()
    clinicians.register(doctor_user.id, doctor_id=doctor.id, hospital_id=hospital.id)
    consent = ConsentService(
        requests=ConsentRequestRepository(session),
        request_categories=ConsentRequestCategoryRepository(session),
        decisions=ConsentDecisionRepository(session),
        grants=ConsentGrantRepository(session),
        audit=AuditLogRepository(session),
        patients=PatientDirectoryService(PatientRepository(session)),
        clinicians=clinicians,
        staff=RecordsStaffDirectory(staff_directory(session)),
        clock=clock,
    )
    service = RecordService(
        records=MedicalRecordRepository(session),
        categories=RecordCategoryRepository(session),
        admins=HospitalAdminRepository(session),
        doctors=DoctorRepository(session),
        hospitals=HospitalRepository(session),
        patients=PatientDirectoryService(PatientRepository(session)),
        storage=storage,
        queue=queue,
        consent=consent,
        grant_scope=consent,
        listing_auditor=consent,
        record_auditor=consent,
        presign_ttl_seconds=300,
        max_upload_bytes=max_upload_bytes,
        clock=clock,
    )
    return Harness(
        service=service,
        consent=consent,
        audit=AuditLogRepository(session),
        categories=RecordCategoryRepository(session),
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
        doctor=doctor,
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
            # Every refusal above is on the record, not silent — including the two by a
            # hospital admin, which ADR-022 brought onto the trail (finding M3-E). Newest
            # first: the clinician's read, the admin's download, the admin's read, and the
            # upload that created the record.
            trail = await h.audit.list_page_by_patient(h.patient.id, after=None, limit=10)
            assert [row.action.value for row in trail] == [
                "ACCESS_DENIED",
                "ACCESS_DENIED",
                "ACCESS_DENIED",
                "RECORD_UPLOADED",
            ]
            assert {row.target_record_id for row in trail} == {locker_view.record.id}
            # The read of a record that does not exist wrote nothing: there is no patient
            # to attribute it to, and no data was reached.
            assert len(trail) == 4

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

            # All five share one date_of_service, so every page boundary lands inside a tie
            # and the id tie-breaker is the only thing making the walk total.
            seen: list[UUID] = []
            after: DateCursor | None = None
            pages = 0
            while True:
                page = await h.service.list_for_caller(
                    h.patient_caller, category_code=None, after=after, limit=2
                )
                seen.extend(v.record.id for v in page.items)
                pages += 1
                if page.next_cursor is None:
                    break
                after = decode_date_cursor(page.next_cursor)
            assert set(seen) == created
            assert len(seen) == len(created)  # nothing served twice
            assert pages == 3  # 2 + 2 + 1

    asyncio.run(scenario())


# -- existence projection (M4.1) ---------------------------------------------------------


async def _upload(h: Harness, code: str) -> RecordView:
    return await h.service.upload_for_health_id(
        h.admin_caller,
        patient_health_id=h.patient.health_id,
        category_code=code,
        date_of_service=date(2026, 3, 1),
        description=None,
        file=PDF,
    )


def test_existence_lists_only_categories_the_patient_holds() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _upload(h, "CBC")
            await _upload(h, "CBC")
            await _upload(h, "XRAY")

            found = await h.service.list_existing_categories(
                h.doctor_caller, patient_health_id=h.patient.health_id
            )

            # Grouped, and ordered by the vocabulary rather than by upload order.
            assert [category.code for category in found] == ["CBC", "XRAY"]

    asyncio.run(scenario())


def test_existence_is_empty_when_the_patient_holds_nothing() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)

            assert (
                await h.service.list_existing_categories(
                    h.doctor_caller, patient_health_id=h.patient.health_id
                )
                == []
            )

    asyncio.run(scenario())


def test_existence_accepts_a_desk_typed_health_id() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _upload(h, "CBC")

            found = await h.service.list_existing_categories(
                h.doctor_caller, patient_health_id=f"  {h.patient.health_id.lower()} "
            )

            assert [category.code for category in found] == ["CBC"]

    asyncio.run(scenario())


def test_existence_excludes_records_the_patient_has_hidden() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _upload(h, "CBC")
            rows = await MedicalRecordRepository(session).list_page(
                patient_id=h.patient.id, limit=10
            )
            rows[0][0].is_hidden = True
            await session.flush()

            assert (
                await h.service.list_existing_categories(
                    h.doctor_caller, patient_health_id=h.patient.health_id
                )
                == []
            )

    asyncio.run(scenario())


def test_a_suspended_clinician_cannot_discover_records() -> None:
    """ADR-015: a non-ACTIVE doctor keeps no clinical capability, discovery included."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _upload(h, "CBC")
            h.doctor.status = DoctorStatus.DISABLED
            await session.flush()

            with pytest.raises(ClinicianNotActiveError):
                await h.service.list_existing_categories(
                    h.doctor_caller, patient_health_id=h.patient.health_id
                )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "status", [HospitalVerificationStatus.SUSPENDED, HospitalVerificationStatus.PENDING]
)
def test_a_non_verified_hospital_initiates_no_discovery(
    status: HospitalVerificationStatus,
) -> None:
    """ADR-034: an ACTIVE clinician of a SUSPENDED (or never-verified) hospital starts no new
    discovery. Refused before the Health ID is resolved: a known and an unknown Health ID get
    the same error, so the refusal says nothing about any patient."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _upload(h, "CBC")
            h.hospital.verification_status = status
            await session.flush()

            for health_id in (h.patient.health_id, "PHI-IND-2026-0000000"):
                with pytest.raises(HospitalNotVerifiedError):
                    await h.service.list_existing_categories(
                        h.doctor_caller, patient_health_id=health_id
                    )

            h.hospital.verification_status = HospitalVerificationStatus.VERIFIED
            await session.flush()
            found = await h.service.list_existing_categories(
                h.doctor_caller, patient_health_id=h.patient.health_id
            )
            assert [category.code for category in found] == ["CBC"]

    asyncio.run(scenario())


def test_existence_requires_a_clinician_profile() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            ghost = AuthenticatedUser(user_id=uuid4(), firebase_uid="fb-ghost", role=Role.DOCTOR)

            with pytest.raises(ProfileNotFoundError):
                await h.service.list_existing_categories(
                    ghost, patient_health_id=h.patient.health_id
                )

    asyncio.run(scenario())


def test_existence_rejects_an_unknown_health_id() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)

            with pytest.raises(UnknownPatientError):
                await h.service.list_existing_categories(
                    h.doctor_caller, patient_health_id="PHI-IND-2026-0000000"
                )

    asyncio.run(scenario())


def test_discovery_writes_no_audit_event() -> None:
    """No record was accessed, so the trail records nothing — see the router docstring."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _upload(h, "CBC")
            before = len(await h.audit.list_page_by_patient(h.patient.id, after=None, limit=99))

            await h.service.list_existing_categories(
                h.doctor_caller, patient_health_id=h.patient.health_id
            )

            after = await h.audit.list_page_by_patient(h.patient.id, after=None, limit=99)
            assert len(after) == before

    asyncio.run(scenario())


# -- granted-record listing (M4.3, ADR-020) ----------------------------------------------


async def _category_ids(h: Harness, *codes: str) -> list[UUID]:
    ids: list[UUID] = []
    for code in codes:
        category = await h.categories.get_by_code(code)
        assert category is not None
        ids.append(category.id)
    return ids


async def _grant(h: Harness, *codes: str, ttl: timedelta = timedelta(days=30)) -> list[UUID]:
    """Give the harness clinician a live grant per category, through the real consent flow.

    Built by request → approve rather than by inserting a ConsentGrant, because a grant is
    only reachable through the decision it derives from (the ``decision_id`` foreign key),
    and a fabricated one would test a state the application cannot produce.
    """
    ids = await _category_ids(h, *codes)
    view = await h.consent.create_request(
        h.doctor_caller,
        patient_health_id=h.patient.health_id,
        category_ids=ids,
        purpose="continuity of care",
    )
    outcome = await h.consent.approve_categories(
        h.patient_caller, view.request.id, ids, grant_ttl=ttl
    )
    return [grant.id for grant in outcome.grants]


async def _list_granted(h: Harness, *, limit: int = 20, after: DateCursor | None = None):  # type: ignore[no-untyped-def]
    return await h.service.list_shared_for_clinician(
        h.doctor_caller, patient_health_id=h.patient.health_id, after=after, limit=limit
    )


async def _actions(h: Harness) -> list[str]:
    trail = await h.audit.list_page_by_patient(h.patient.id, after=None, limit=99)
    return [row.action.value for row in trail]


def test_a_grant_reveals_the_record_ids_it_covers_and_nothing_else() -> None:
    """The capability ADR-020 adds: a consented clinician can finally address a record."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _upload(h, "CBC")
            await _upload(h, "MRI")
            await _grant(h, "CBC")

            page = await _list_granted(h)

            assert [view.category.code for view in page.items] == ["CBC"]
            assert [category.code for category in page.granted_categories] == ["CBC"]
            assert page.next_cursor is None

    asyncio.run(scenario())


def test_a_revoked_grant_stops_revealing_records_immediately() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _upload(h, "CBC")
            (grant_id,) = await _grant(h, "CBC")
            assert len((await _list_granted(h)).items) == 1

            await h.consent.revoke_grant(h.patient_caller, grant_id)

            page = await _list_granted(h)
            assert page.items == [] and page.granted_categories == []

    asyncio.run(scenario())


def test_an_expired_grant_reveals_nothing() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _upload(h, "CBC")
            await _grant(h, "CBC", ttl=timedelta(seconds=-1))

            assert (await _list_granted(h)).items == []

    asyncio.run(scenario())


def test_a_grant_expiring_at_this_very_instant_does_not_count() -> None:
    """The boundary the listing shares with ``enforce``: ``expires_at > at``, strictly.

    A frozen clock is the only way to put ``expires_at`` exactly on the instant the listing
    is judged at, which is what distinguishes "> now" from ">= now". The deadline is set on
    the row rather than through ``grant_ttl`` because the service floors a zero TTL to its
    configured default.
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            frozen = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
            h = await _harness(session, clock=lambda: frozen)
            await _upload(h, "CBC")
            (grant_id,) = await _grant(h, "CBC")
            grants = ConsentGrantRepository(session)

            grant = await grants.get_by_id(grant_id)
            assert grant is not None
            grant.expires_at = frozen
            await session.flush()
            assert as_utc(grant.expires_at) == frozen
            assert (await _list_granted(h)).items == []

            # One microsecond of life left is still life — the predicate is strict, not off
            # by one in the other direction.
            grant.expires_at = frozen + timedelta(microseconds=1)
            await session.flush()
            assert len((await _list_granted(h)).items) == 1

    asyncio.run(scenario())


def test_a_hidden_record_stays_hidden_from_a_consented_clinician() -> None:
    """docs/DOMAIN_MODEL.md §1: hiding withdraws a record from what consent can share, so
    a live grant for its category is not enough — as at every other clinician read."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _upload(h, "CBC")
            await _upload(h, "CBC")
            await _grant(h, "CBC")
            rows = await MedicalRecordRepository(session).list_page(
                patient_id=h.patient.id, limit=9
            )
            rows[0][0].is_hidden = True
            await session.flush()

            page = await _list_granted(h)

            assert [view.record.id for view in page.items] == [rows[1][0].id]
            # The category still lists: the patient approved it, and one hidden document
            # does not withdraw the approval.
            assert [category.code for category in page.granted_categories] == ["CBC"]

    asyncio.run(scenario())


def test_a_grant_for_one_patient_reveals_nothing_about_another() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            other_user = User(firebase_uid=f"fb-other-{uuid4()}", role=Role.PATIENT)
            session.add(other_user)
            await session.flush()
            other = Patient(
                user_id=other_user.id, health_id="PHI-IND-2026-2QE8DVR", full_name="Other (Demo)"
            )
            session.add(other)
            await session.flush()
            await h.service.upload_for_health_id(
                h.admin_caller,
                patient_health_id=other.health_id,
                category_code="CBC",
                date_of_service=date(2026, 3, 1),
                description=None,
                file=PDF,
            )
            await _grant(h, "CBC")  # granted by h.patient, not by `other`

            covered = await _list_granted(h)
            assert covered.items == []  # h.patient holds no CBC record of their own

            uncovered = await h.service.list_shared_for_clinician(
                h.doctor_caller, patient_health_id=other.health_id, after=None, limit=20
            )
            assert uncovered.items == [] and uncovered.granted_categories == []

    asyncio.run(scenario())


def test_a_suspended_clinician_cannot_list_granted_records() -> None:
    """ADR-015, and refused rather than emptied: a suspended doctor is told their profile
    is inactive, exactly as at ``/records/existence``."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _upload(h, "CBC")
            await _grant(h, "CBC")
            h.doctor.status = DoctorStatus.DISABLED
            await session.flush()

            with pytest.raises(ClinicianNotActiveError):
                await _list_granted(h)

    asyncio.run(scenario())


def test_listing_requires_a_clinician_profile_and_a_real_health_id() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            with pytest.raises(UnknownPatientError):
                await h.service.list_shared_for_clinician(
                    h.doctor_caller,
                    patient_health_id="PHI-IND-2026-0000000",
                    after=None,
                    limit=20,
                )
            with pytest.raises(ProfileNotFoundError):
                await h.service.list_shared_for_clinician(
                    h.admin_caller, patient_health_id=h.patient.health_id, after=None, limit=20
                )

    asyncio.run(scenario())


def test_no_grant_returns_an_empty_page_that_never_touched_medical_records() -> None:
    """The short-circuit, proved structurally rather than by counting statements.

    ``list_page_for_grantee`` refuses an empty category set (a grant-free listing is not
    expressible), so had the service queried records here this call would have raised
    instead of returning a page.
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _upload(h, "CBC")

            page = await _list_granted(h)

            assert page.items == [] and page.granted_categories == [] and page.next_cursor is None

    asyncio.run(scenario())


def test_an_empty_scope_is_audited_as_a_refusal() -> None:
    """A clinician asking what they may read has been answered "nothing", and the patient
    is entitled to see that they asked."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _upload(h, "CBC")

            await _list_granted(h)

            # Newest first: the refused listing, then the upload that set the scene — which
            # is itself an audited event since ADR-022.
            assert await _actions(h) == ["ACCESS_DENIED", "RECORD_UPLOADED"]

    asyncio.run(scenario())


def test_a_served_listing_writes_one_records_listed_event_with_no_target() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _upload(h, "CBC")
            await _grant(h, "CBC")

            await _list_granted(h)

            trail = await h.audit.list_page_by_patient(h.patient.id, after=None, limit=99)
            listed = [row for row in trail if row.action is AuditAction.RECORDS_LISTED]
            assert len(listed) == 1
            event = listed[0]
            assert event.actor_user_id == h.doctor_caller.user_id
            assert event.actor_role is Role.DOCTOR
            # A scope-level event fills none of the three target columns (ADR-020); the
            # patient it concerns is carried by patient_id, which is never null.
            assert event.target_record_id is None
            assert event.target_category_id is None
            assert event.target_request_id is None

    asyncio.run(scenario())


def test_one_audit_row_per_listing_however_many_records_it_returns() -> None:
    """The regression test for the design decision: audit volume must track *requests*,
    not rows, or a page-sized burst buries the patient's trail and costs an anchor apiece
    at M6 (ADR-004)."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            for _ in range(5):
                await _upload(h, "CBC")
            await _grant(h, "CBC")

            small = await _list_granted(h, limit=1)
            assert len(small.items) == 1
            assert (await _actions(h)).count("RECORDS_LISTED") == 1

            large = await _list_granted(h, limit=100)
            assert len(large.items) == 5
            assert (await _actions(h)).count("RECORDS_LISTED") == 2

    asyncio.run(scenario())


def test_the_listing_paginates_newest_first_over_a_stable_cursor() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            for _ in range(3):
                await _upload(h, "CBC")
            await _grant(h, "CBC")

            first = await _list_granted(h, limit=2)
            assert len(first.items) == 2 and first.next_cursor is not None
            second = await _list_granted(h, limit=2, after=decode_date_cursor(first.next_cursor))

            assert len(second.items) == 1 and second.next_cursor is None
            seen = [view.record.id for view in [*first.items, *second.items]]
            assert len(set(seen)) == 3
            newest_first = [view.record.created_at for view in [*first.items, *second.items]]
            assert newest_first == sorted(newest_first, reverse=True)

    asyncio.run(scenario())


def test_the_scope_is_reported_even_when_the_patient_holds_nothing_in_it() -> None:
    """ "Nothing was approved" and "what was approved is empty" are different answers, and
    only ``granted_categories`` distinguishes them."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _upload(h, "MRI")
            await _grant(h, "CBC")

            page = await _list_granted(h)

            assert page.items == []
            assert [category.code for category in page.granted_categories] == ["CBC"]

    asyncio.run(scenario())


def test_granted_categories_follow_the_vocabulary_order() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _grant(h, "XRAY", "CBC")

            page = await _list_granted(h)

            assert [category.code for category in page.granted_categories] == ["CBC", "XRAY"]

    asyncio.run(scenario())


def test_a_listing_costs_the_same_number_of_statements_at_any_page_size() -> None:
    """The N+1 guard, and the reason ``enforce`` is not called per record.

    Per-record enforcement would cost two lookups and an audit insert for every row; this
    resolves the scope once and reads the page in one joined statement, so the cost of a
    listing is a property of the request, not of how much the patient holds.
    """

    async def scenario() -> None:
        async with sqlite_session_with_engine() as (session, engine):
            h = await _harness(session)
            for _ in range(10):
                await _upload(h, "CBC")
            await _grant(h, "CBC")
            await session.flush()

            with counting_statements(engine) as one:
                assert len((await _list_granted(h, limit=1)).items) == 1
            with counting_statements(engine) as ten:
                assert len((await _list_granted(h, limit=10)).items) == 10

            assert len(one) == len(ten)
            # Six, and always six: the clinician, the patient, the granted category set,
            # the audit insert, the category vocabulary, and the page itself — category and
            # hospital ride the page's joins, so no row costs a statement of its own. (In
            # production the clinician directory is a real adapter and adds one more; this
            # harness resolves it in memory. What matters is that neither number moves with
            # the page size.)
            assert len(ten) == 6

    asyncio.run(scenario())


# -- ADR-022: the events that never reach the consent choke point ----------------------------


async def _trail(h: Harness) -> list[AuditLog]:
    """The patient's trail, oldest first — the order the actions happened in."""
    rows = await h.audit.list_page_by_patient(h.patient.id, after=None, limit=99)
    return list(reversed(rows))


def test_a_hospital_upload_writes_exactly_one_record_uploaded_event() -> None:
    """RECORD_UPLOADED has been in the vocabulary since M0.2 and was written by nothing:
    a document could enter a patient's history leaving no trace of who put it there."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)

            view = await h.service.upload_for_health_id(
                h.admin_caller,
                patient_health_id=h.patient.health_id,
                category_code="CBC",
                date_of_service=date(2026, 3, 1),
                description=None,
                file=PDF,
                request_context="req-upload",
            )

            trail = await _trail(h)
            assert len(trail) == 1
            event = trail[0]
            assert event.action is AuditAction.RECORD_UPLOADED
            assert event.actor_user_id == h.admin_caller.user_id
            assert event.actor_role is Role.HOSPITAL_ADMIN
            assert event.patient_id == h.patient.id
            assert event.target_record_id == view.record.id
            assert event.request_context == "req-upload"
            # At most one target (docs/DOMAIN_MODEL.md §1, as relaxed by ADR-020).
            assert (event.target_category_id, event.target_request_id) == (None, None)

    asyncio.run(scenario())


def test_the_upload_event_carries_no_clinical_payload() -> None:
    """Audit metadata only: the trail says an upload happened, never what was in it."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            named = FileUpload(
                filename="hiv-panel-positive.pdf",
                content_type="application/pdf",
                data=b"%PDF-1.7 confidential",
            )

            await h.service.upload_for_health_id(
                h.admin_caller,
                patient_health_id=h.patient.health_id,
                category_code="CBC",
                date_of_service=date(2026, 3, 1),
                description="Routine pre-operative panel",
                file=named,
                request_context=None,
            )

            row = (await _trail(h))[0]
            written = " ".join(str(value) for value in row.__dict__.values())
            assert "hiv-panel-positive" not in written
            assert "confidential" not in written
            assert "pre-operative" not in written

    asyncio.run(scenario())


def test_a_patient_locker_upload_is_audited_to_the_patient_as_actor() -> None:
    """RECORD_UPLOADED is unqualified in the vocabulary, and a trail that recorded only
    hospital uploads would be a trail that lies by omission about the patient's own."""

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

            event = (await _trail(h))[0]
            assert event.action is AuditAction.RECORD_UPLOADED
            assert event.actor_user_id == h.patient_caller.user_id
            assert event.actor_role is Role.PATIENT
            assert event.target_record_id == view.record.id

    asyncio.run(scenario())


def test_a_failed_upload_writes_no_event() -> None:
    """Failures must not create misleading success events: the storage write happens before
    the audit write, and the transaction carries both away together if anything fails."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            h.storage.storage_error = StorageUnavailableError()

            with pytest.raises(StorageUnavailableError):
                await h.service.upload_for_health_id(
                    h.admin_caller,
                    patient_health_id=h.patient.health_id,
                    category_code="CBC",
                    date_of_service=date(2026, 3, 1),
                    description=None,
                    file=PDF,
                )

            assert await _trail(h) == []

    asyncio.run(scenario())


def test_a_hospitals_own_upload_read_is_now_audited() -> None:
    """Finding M3-E, closed: the read is still decided by layer 2 and still never reaches
    the choke point, but the patient can now see that it happened."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            view = await _upload(h, "CBC")

            await h.service.get_for_caller(
                h.admin_caller, view.record.id, request_context="req-read"
            )

            event = (await _trail(h))[-1]
            assert event.action is AuditAction.RECORD_VIEWED
            assert event.actor_user_id == h.admin_caller.user_id
            assert event.actor_role is Role.HOSPITAL_ADMIN
            assert event.target_record_id == view.record.id
            assert event.request_context == "req-read"

    asyncio.run(scenario())


def test_a_hospital_download_is_distinguished_from_a_view() -> None:
    """The listing / view / download distinction the vocabulary draws is preserved."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            view = await _upload(h, "CBC")

            await h.service.create_download_link(h.admin_caller, view.record.id)

            actions = [row.action for row in await _trail(h)]
            assert actions == [AuditAction.RECORD_UPLOADED, AuditAction.RECORD_DOWNLOADED]

    asyncio.run(scenario())


def test_one_hospital_read_produces_exactly_one_event() -> None:
    """No duplicate events: a metadata read must not also emit a listing or a download."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            view = await _upload(h, "CBC")
            before = len(await _trail(h))

            await h.service.get_for_caller(h.admin_caller, view.record.id)

            assert len(await _trail(h)) == before + 1

    asyncio.run(scenario())


def test_a_hospital_read_of_another_hospitals_record_is_audited_as_denied() -> None:
    """The other half of M3-E, on ADR-018's terms: a refusal the patient could not see is
    exactly the event a patient most needs to see."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            locker = await h.service.upload_to_own_locker(
                h.patient_caller,
                category_code="CBC",
                date_of_service=date(2026, 3, 1),
                description=None,
                file=PDF,
            )

            with pytest.raises(RecordNotFoundError):
                await h.service.get_for_caller(h.admin_caller, locker.record.id)

            event = (await _trail(h))[-1]
            assert event.action is AuditAction.ACCESS_DENIED
            assert event.actor_user_id == h.admin_caller.user_id
            assert event.actor_role is Role.HOSPITAL_ADMIN
            assert event.target_record_id == locker.record.id

    asyncio.run(scenario())


def test_reading_a_record_that_does_not_exist_writes_nothing() -> None:
    """There is no patient to attribute it to — audit_logs.patient_id is NOT NULL — and no
    data was reached, so there is nothing to record."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            await _upload(h, "CBC")
            before = await _trail(h)

            with pytest.raises(RecordNotFoundError):
                await h.service.get_for_caller(h.admin_caller, uuid4())

            assert await _trail(h) == before

    asyncio.run(scenario())


def test_patient_and_clinician_read_behaviour_is_unchanged() -> None:
    """The paths that already went through the choke point still do, once each."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            h = await _harness(session)
            view = await _upload(h, "CBC")

            await h.service.get_for_caller(h.patient_caller, view.record.id)
            owner_event = (await _trail(h))[-1]

            with pytest.raises(RecordNotFoundError):
                await h.service.get_for_caller(h.doctor_caller, view.record.id)
            clinician_event = (await _trail(h))[-1]

            assert owner_event.action is AuditAction.RECORD_VIEWED
            assert owner_event.actor_role is Role.PATIENT
            assert clinician_event.action is AuditAction.ACCESS_DENIED
            assert clinician_event.actor_role is Role.DOCTOR

    asyncio.run(scenario())
