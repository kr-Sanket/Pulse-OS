"""Records domain service: upload → object storage, metadata queries, presigned downloads.

M2 scope (ROADMAP): the only read relationships are ADR-013 **layer 2** — a patient reads
their own records; a hospital admin reads records their hospital uploaded. Doctors have NO
read path here: doctor access is consent-gated and arrives with the consent module (M3),
which will add the ``consent.enforce()`` dependency + audit write in front of these reads
(docs/SYSTEM_ARCHITECTURE.md rule 3). Nothing in this service may widen access before that.

Framework-free; owns no transaction. The object-storage write happens AFTER the metadata
flush, so a DB failure never leaves a file behind, and a storage failure rolls back the
row (an orphan object is only possible if the final request commit itself fails — rare,
harmless, unreferenced).
"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Final
from uuid import UUID, uuid4

from app.core.queue import JobQueue, QueueUnavailableError
from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.patients.directory import PatientDirectoryService
from app.modules.records.errors import (
    EmptyFileError,
    FileTooLargeError,
    HospitalNotVerifiedError,
    ProfileNotFoundError,
    RecordNotFoundError,
    UnknownCategoryError,
    UnknownPatientError,
    UnsupportedFileTypeError,
)
from app.modules.records.models import (
    Hospital,
    HospitalVerificationStatus,
    MedicalRecord,
    RecordCategory,
    RecordOrigin,
)
from app.modules.records.repository import (
    HospitalAdminRepository,
    HospitalRepository,
    MedicalRecordRepository,
    RecordCategoryRepository,
    RecordRow,
)
from app.modules.records.storage import ObjectStorage
from app.shared.pagination import CursorKey, encode_cursor

logger = logging.getLogger(__name__)

#: Accepted medical-document formats (docs/PROJECT_OVERVIEW.md: reports are PDFs/scans).
ALLOWED_CONTENT_TYPES: Final = ("application/pdf", "image/jpeg", "image/png")

#: Worker task emitted per upload (ADR-014); the M5 pipeline consumes it.
RECORD_UPLOADED_TASK: Final = "record_uploaded"


@dataclass(frozen=True, slots=True)
class FileUpload:
    """The validated-at-the-boundary upload payload, already fully read into memory
    (the router enforces the size cap while reading)."""

    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class RecordView:
    record: MedicalRecord
    category: RecordCategory
    hospital: Hospital | None


@dataclass(frozen=True, slots=True)
class RecordPage:
    items: list[RecordView]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class DownloadLink:
    url: str
    expires_in_seconds: int


class RecordService:
    def __init__(
        self,
        records: MedicalRecordRepository,
        categories: RecordCategoryRepository,
        admins: HospitalAdminRepository,
        hospitals: HospitalRepository,
        patients: PatientDirectoryService,
        storage: ObjectStorage,
        queue: JobQueue,
        *,
        presign_ttl_seconds: int,
        max_upload_bytes: int,
    ) -> None:
        self._records = records
        self._categories = categories
        self._admins = admins
        self._hospitals = hospitals
        self._patients = patients
        self._storage = storage
        self._queue = queue
        self._presign_ttl_seconds = presign_ttl_seconds
        self.max_upload_bytes = max_upload_bytes

    # -- uploads ---------------------------------------------------------------------

    async def upload_for_health_id(
        self,
        caller: AuthenticatedUser,
        *,
        patient_health_id: str,
        category_code: str,
        date_of_service: date,
        description: str | None,
        file: FileUpload,
    ) -> RecordView:
        """Hospital admin uploads a record against a patient's Health ID (the M2 gate
        flow). Requires a VERIFIED hospital (ADR-015)."""
        self._validate_file(file)
        admin = await self._admins.get_by_user_id(caller.user_id)
        if admin is None:
            raise ProfileNotFoundError()
        hospital = await self._hospitals.get_by_id(admin.hospital_id)
        if hospital is None:
            raise ProfileNotFoundError()
        if hospital.verification_status is not HospitalVerificationStatus.VERIFIED:
            raise HospitalNotVerifiedError()
        patient = await self._patients.get_by_health_id(patient_health_id)
        if patient is None:
            raise UnknownPatientError()
        category = await self._resolve_category(category_code)
        record = await self._store(
            patient_id=patient.id,
            category=category,
            origin=RecordOrigin.HOSPITAL_UPLOAD,
            uploaded_by_hospital_id=hospital.id,
            date_of_service=date_of_service,
            description=description,
            file=file,
        )
        return RecordView(record=record, category=category, hospital=hospital)

    async def upload_to_own_locker(
        self,
        caller: AuthenticatedUser,
        *,
        category_code: str,
        date_of_service: date,
        description: str | None,
        file: FileUpload,
    ) -> RecordView:
        """Patient uploads to their own medical locker (RBAC: own locker only)."""
        self._validate_file(file)
        patient = await self._patients.get_by_user_id(caller.user_id)
        if patient is None:
            raise ProfileNotFoundError()
        category = await self._resolve_category(category_code)
        record = await self._store(
            patient_id=patient.id,
            category=category,
            origin=RecordOrigin.PATIENT_LOCKER,
            uploaded_by_hospital_id=None,
            date_of_service=date_of_service,
            description=description,
            file=file,
        )
        return RecordView(record=record, category=category, hospital=None)

    # -- reads (ADR-013 layer 2 only at M2 — see module docstring) --------------------

    async def list_for_caller(
        self,
        caller: AuthenticatedUser,
        *,
        category_code: str | None,
        after: CursorKey | None,
        limit: int,
    ) -> RecordPage:
        """The caller's relationship-scoped record listing, newest first."""
        category_id: UUID | None = None
        if category_code is not None:
            category_id = (await self._resolve_category(category_code)).id
        if caller.role is Role.PATIENT:
            patient = await self._patients.get_by_user_id(caller.user_id)
            if patient is None:
                raise ProfileNotFoundError()
            rows = await self._records.list_page(
                patient_id=patient.id, category_id=category_id, after=after, limit=limit + 1
            )
        else:  # HOSPITAL_ADMIN (the router's role gate admits no other role)
            admin = await self._admins.get_by_user_id(caller.user_id)
            if admin is None:
                raise ProfileNotFoundError()
            rows = await self._records.list_page(
                uploaded_by_hospital_id=admin.hospital_id,
                category_id=category_id,
                after=after,
                limit=limit + 1,
            )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = None
        if has_more:
            last = page[-1][0]
            next_cursor = encode_cursor(CursorKey(created_at=last.created_at, item_id=last.id))
        return RecordPage(items=[self._to_view(row) for row in page], next_cursor=next_cursor)

    async def get_for_caller(self, caller: AuthenticatedUser, record_id: UUID) -> RecordView:
        """Single record metadata; outside the caller's relationship scope it is
        indistinguishable from nonexistent (404-not-403, docs/API_GUIDELINES.md)."""
        row = await self._records.get_with_context(record_id)
        if row is None or not await self._caller_may_read(caller, row[0]):
            raise RecordNotFoundError()
        return self._to_view(row)

    async def create_download_link(
        self, caller: AuthenticatedUser, record_id: UUID
    ) -> DownloadLink:
        """Short-lived presigned URL for the record's file, issued only after the
        relationship check. M3 wires ``consent.enforce()`` + the audit write in front of
        this — file access is already funneled through this single method."""
        view = await self.get_for_caller(caller, record_id)
        url = await self._storage.create_download_url(
            view.record.s3_key,
            expires_in_seconds=self._presign_ttl_seconds,
            filename=view.record.original_filename,
            content_type=view.record.content_type,
        )
        return DownloadLink(url=url, expires_in_seconds=self._presign_ttl_seconds)

    async def list_categories(self) -> list[RecordCategory]:
        return await self._categories.list_all()

    # -- internals ---------------------------------------------------------------------

    def _validate_file(self, file: FileUpload) -> None:
        if file.content_type not in ALLOWED_CONTENT_TYPES:
            raise UnsupportedFileTypeError(ALLOWED_CONTENT_TYPES)
        if len(file.data) == 0:
            raise EmptyFileError()
        if len(file.data) > self.max_upload_bytes:
            raise FileTooLargeError(self.max_upload_bytes)

    async def _resolve_category(self, code: str) -> RecordCategory:
        category = await self._categories.get_by_code(code.strip().upper())
        if category is None:
            raise UnknownCategoryError()
        return category

    async def _store(
        self,
        *,
        patient_id: UUID,
        category: RecordCategory,
        origin: RecordOrigin,
        uploaded_by_hospital_id: UUID | None,
        date_of_service: date,
        description: str | None,
        file: FileUpload,
    ) -> MedicalRecord:
        record_id = uuid4()
        # UUIDs only in the object key — filenames leak information (docs/SECURITY.md).
        s3_key = f"records/{patient_id}/{record_id}"
        record = await self._records.add(
            MedicalRecord(
                id=record_id,
                patient_id=patient_id,
                category_id=category.id,
                origin=origin,
                uploaded_by_hospital_id=uploaded_by_hospital_id,
                date_of_service=date_of_service,
                description=description,
                original_filename=file.filename,
                content_type=file.content_type,
                size_bytes=len(file.data),
                s3_key=s3_key,
            )
        )
        await self._storage.put_object(s3_key, file.data, content_type=file.content_type)
        try:
            await self._queue.enqueue(RECORD_UPLOADED_TASK, record_id=str(record_id))
        except QueueUnavailableError:
            # ADR-014: the job is advisory until M5 — the upload must not fail with Redis.
            logger.warning("record_uploaded enqueue failed", extra={"record_id": str(record_id)})
        return record

    async def _caller_may_read(self, caller: AuthenticatedUser, record: MedicalRecord) -> bool:
        if caller.role is Role.PATIENT:
            patient = await self._patients.get_by_user_id(caller.user_id)
            return patient is not None and record.patient_id == patient.id
        if caller.role is Role.HOSPITAL_ADMIN:
            admin = await self._admins.get_by_user_id(caller.user_id)
            return (
                admin is not None
                and record.uploaded_by_hospital_id is not None
                and record.uploaded_by_hospital_id == admin.hospital_id
            )
        return False  # DOCTOR waits for consent (M3); SYSTEM_ADMIN never reads content

    def _to_view(self, row: RecordRow) -> RecordView:
        record, category, hospital = row
        return RecordView(record=record, category=category, hospital=hospital)
