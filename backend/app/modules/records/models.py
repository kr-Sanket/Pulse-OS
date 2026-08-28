"""records-owned tables (docs/DOMAIN_MODEL.md §1: MedicalRecord, RecordCategory).

FHIR DocumentReference-aligned metadata (ADR-006). Files live in S3/MinIO (ADR-005);
only metadata and object keys are persisted here (docs/DATABASE_DESIGN.md principle 2).
"""

import uuid
from datetime import date
from enum import StrEnum
from typing import Final

from sqlalchemy import BigInteger, Boolean, Date, Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RecordOrigin(StrEnum):
    """Origin of the medical record (docs/DOMAIN_MODEL.md §1)."""

    HOSPITAL_UPLOAD = "HOSPITAL_UPLOAD"
    PATIENT_LOCKER = "PATIENT_LOCKER"


class ProcessingStatus(StrEnum):
    """Async ingestion pipeline processing status (ADR-008, docs/AI_ARCHITECTURE.md)."""

    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"


DEFAULT_RECORD_CATEGORIES: Final[tuple[tuple[str, str, str], ...]] = (
    ("CBC", "Complete Blood Count", "Full blood count and hemogram reports."),
    ("LAB_REPORT", "Lab Report", "General biochemistry, pathology, and diagnostic lab reports."),
    ("MRI", "MRI Scan", "Magnetic resonance imaging diagnostic reports and scans."),
    ("XRAY", "X-Ray", "Plain radiography and X-ray imaging reports."),
    ("CT_SCAN", "CT Scan", "Computed tomography imaging reports and scans."),
    ("ULTRASOUND", "Ultrasound", "Ultrasonography and Doppler diagnostic reports."),
    ("PRESCRIPTION", "Prescription", "Doctor consultations, prescriptions, and dosage directions."),
    ("DISCHARGE_SUMMARY", "Discharge Summary", "Hospital inpatient discharge summaries and notes."),
    ("VACCINATION", "Vaccination Record", "Immunization and vaccination records."),
    ("OTHER", "Other Clinical Document", "Other medical reports, clinical summaries, and files."),
)


class RecordCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Controlled vocabulary for consent granularity (docs/DOMAIN_MODEL.md §1).
    A seedable table rather than a hard-coded enum so new categories can be added
    without logic migrations.
    """

    __tablename__ = "record_categories"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)


class MedicalRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Metadata for one clinical document (FHIR DocumentReference-aligned).
    Belongs to exactly one Patient. Accessible only through consent.enforce() (ADR-013).
    """

    __tablename__ = "medical_records"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("patients.id"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("record_categories.id"), nullable=False, index=True
    )
    origin: Mapped[RecordOrigin] = mapped_column(
        Enum(
            RecordOrigin,
            name="record_origin",
            native_enum=False,
            length=30,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    hospital_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("hospitals.id"), nullable=True, index=True
    )
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("doctors.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    service_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(
            ProcessingStatus,
            name="processing_status",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=ProcessingStatus.UPLOADED,
    )
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
