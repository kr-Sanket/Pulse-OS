"""Records domain service: medical record metadata lifecycle and category vocabularies.

Framework-free; owns no transaction — the request scope commits (app/core/db.py).
Cross-module boundaries use explicit service interfaces
(PatientService, HospitalService, DoctorService).

CRITICAL SECURITY PROPERTY:
This service manages record persistence and category summaries. It DOES NOT provide
an unauthenticated or unconsented read path for clinicians. Clinical content access
is enforced exclusively by the consent module at runtime (ADR-013).
"""

from collections.abc import Sequence
from datetime import date
from uuid import UUID

from app.modules.doctors.service import DoctorService
from app.modules.hospitals.service import HospitalService
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
    MedicalRecord,
    ProcessingStatus,
    RecordCategory,
    RecordOrigin,
)
from app.modules.records.repository import (
    MedicalRecordRepository,
    RecordCategoryRepository,
)
from app.modules.records.schemas import CategoryExistenceSummary


class RecordService:
    def __init__(
        self,
        records: MedicalRecordRepository,
        categories: RecordCategoryRepository,
        patients: PatientService,
        hospitals: HospitalService,
        doctors: DoctorService,
    ) -> None:
        self._records = records
        self._categories = categories
        self._patients = patients
        self._hospitals = hospitals
        self._doctors = doctors

    async def create_category(
        self,
        *,
        code: str,
        display_name: str,
        description: str | None = None,
    ) -> RecordCategory:
        clean_code = code.strip().upper()
        clean_name = display_name.strip()
        clean_desc = description.strip() if description is not None else None

        if not clean_code:
            raise RecordValidationError("Category code must not be blank.")
        if not clean_name:
            raise RecordValidationError("Category display name must not be blank.")

        category = RecordCategory(
            code=clean_code,
            display_name=clean_name,
            description=clean_desc,
        )
        return await self._categories.add(category)

    async def get_category_by_id(self, id: UUID) -> RecordCategory | None:
        return await self._categories.get_by_id(id)

    async def get_category_by_code(self, code: str) -> RecordCategory | None:
        return await self._categories.get_by_code(code.strip().upper())

    async def list_categories(self) -> Sequence[RecordCategory]:
        return await self._categories.list_all()

    async def seed_default_categories(self) -> list[RecordCategory]:
        """Seed any missing standard categories defined in DOMAIN_MODEL.md."""
        seeded: list[RecordCategory] = []
        for code, display_name, description in DEFAULT_RECORD_CATEGORIES:
            existing = await self.get_category_by_code(code)
            if existing is None:
                try:
                    category = await self.create_category(
                        code=code, display_name=display_name, description=description
                    )
                    seeded.append(category)
                except DuplicateCategoryCodeError:
                    pass
        return seeded

    async def create_record(
        self,
        *,
        patient_id: UUID,
        category_id: UUID,
        origin: RecordOrigin,
        title: str,
        s3_key: str,
        file_name: str,
        mime_type: str,
        hospital_id: UUID | None = None,
        doctor_id: UUID | None = None,
        service_date: date | None = None,
        file_size_bytes: int | None = None,
    ) -> MedicalRecord:
        """Create and persist a new clinical document reference."""
        clean_title = title.strip()
        clean_s3_key = s3_key.strip()
        clean_file_name = file_name.strip()
        clean_mime_type = mime_type.strip()

        if not clean_title:
            raise RecordValidationError("Record title must not be blank.")
        if not clean_s3_key:
            raise RecordValidationError("S3 object key must not be blank.")
        if not clean_file_name:
            raise RecordValidationError("File name must not be blank.")
        if not clean_mime_type:
            raise RecordValidationError("MIME type must not be blank.")
        if file_size_bytes is not None and file_size_bytes < 0:
            raise RecordValidationError("File size bytes cannot be negative.")

        # Verify patient existence via patient service boundary
        patient = await self._patients.get_patient_by_id(patient_id)
        if patient is None:
            raise InvalidRecordPatientError("Target patient does not exist.")

        # Verify category existence
        category = await self.get_category_by_id(category_id)
        if category is None:
            raise RecordCategoryNotFoundError("Record category does not exist.")

        # Validate origin rules
        if origin is RecordOrigin.HOSPITAL_UPLOAD:
            if hospital_id is None:
                raise InvalidRecordOriginError("Hospital upload must specify a hospital_id.")
            hospital = await self._hospitals.get_hospital(hospital_id)
            if hospital is None:
                raise InvalidRecordHospitalError("Uploading hospital does not exist.")

            if doctor_id is not None:
                doctor = await self._doctors.get_by_id(doctor_id)
                if doctor is None:
                    raise InvalidRecordDoctorError("Uploading doctor does not exist.")
                if doctor.hospital_id != hospital_id:
                    raise InvalidRecordDoctorError(
                        "Uploading doctor is not affiliated with the uploading hospital."
                    )
        elif origin is RecordOrigin.PATIENT_LOCKER:
            if hospital_id is not None or doctor_id is not None:
                raise InvalidRecordOriginError(
                    "Patient locker uploads must not have hospital or doctor associations."
                )

        record = MedicalRecord(
            patient_id=patient_id,
            category_id=category_id,
            origin=origin,
            hospital_id=hospital_id,
            doctor_id=doctor_id,
            title=clean_title,
            service_date=service_date,
            s3_key=clean_s3_key,
            file_name=clean_file_name,
            mime_type=clean_mime_type,
            file_size_bytes=file_size_bytes,
            processing_status=ProcessingStatus.UPLOADED,
            is_hidden=False,
        )
        return await self._records.add(record)

    async def get_record_by_id(self, id: UUID) -> MedicalRecord | None:
        return await self._records.get_by_id(id)

    async def list_records_for_patient(
        self, patient_id: UUID, *, include_hidden: bool = False
    ) -> Sequence[MedicalRecord]:
        return await self._records.list_by_patient_id(patient_id, include_hidden=include_hidden)

    async def list_records_by_category(
        self, patient_id: UUID, category_id: UUID, *, include_hidden: bool = False
    ) -> Sequence[MedicalRecord]:
        return await self._records.list_by_category_and_patient(
            patient_id, category_id, include_hidden=include_hidden
        )

    async def get_category_existence_summary(
        self, patient_id: UUID
    ) -> list[CategoryExistenceSummary]:
        """Project category-level existence for discovery without exposing metadata (ADR-013)."""
        counts = await self._records.get_category_existence_counts(patient_id)
        return [
            CategoryExistenceSummary(
                category_id=row[0],
                category_code=row[1],
                category_name=row[2],
                hospital_id=row[3],
                record_count=row[4],
            )
            for row in counts
        ]

    async def update_processing_status(
        self,
        record_id: UUID,
        status: ProcessingStatus,
        failure_reason: str | None = None,
    ) -> MedicalRecord:
        record = await self._records.update_status(record_id, status, failure_reason=failure_reason)
        if record is None:
            raise RecordNotFoundError("Medical record not found.")
        return record

    async def set_record_hidden(
        self,
        record_id: UUID,
        patient_id: UUID,
        is_hidden: bool,
    ) -> MedicalRecord:
        record = await self._records.get_by_id(record_id)
        if record is None or record.patient_id != patient_id:
            raise RecordNotFoundError("Medical record not found.")
        if record.origin is not RecordOrigin.PATIENT_LOCKER:
            raise InvalidRecordOriginError("Only patient locker records can be hidden.")

        updated = await self._records.set_hidden(record_id, is_hidden)
        if updated is None:
            raise RecordNotFoundError("Medical record not found.")
        return updated
