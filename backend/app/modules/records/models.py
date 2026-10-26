"""records-owned tables: care organizations, their staff, and record metadata.

``Hospital`` (FHIR Organization) lives here because the conceptual entity map
(docs/DATABASE_DESIGN.md) hangs both DocumentReference and Practitioner off the
Organization, and ROADMAP M2 bundles hospitals with the records milestone. ``Doctor``
(FHIR Practitioner) and ``HospitalAdmin`` follow the same ownership. ``RecordCategory``
is the consent granularity unit — a seedable table, NOT a code enum, so adding a category
never requires a logic migration (docs/DOMAIN_MODEL.md §1). ``MedicalRecord`` is the
FHIR DocumentReference-shaped metadata row — the file itself lives in object storage,
never in the DB (ADR-005).

Cross-module links (``users``, ``patients``) are plain FKs — referential integrity only,
no ORM relationship crosses a module boundary (docs/SYSTEM_ARCHITECTURE.md rule 1).
"""

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _enum_values(enum_cls: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_cls]


class HospitalVerificationStatus(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class HospitalLifecycleAction(StrEnum):
    """Administrative lifecycle actions for hospital verification (ADR-034)."""

    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    REINSTATED = "REINSTATED"


class DoctorStatus(StrEnum):
    """Managed by the doctor's hospital admin (ADR-015): self-registration lands PENDING;
    only ACTIVE doctors pass the relationship layer for clinical capabilities (M3+)."""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class RecordOrigin(StrEnum):
    """docs/DOMAIN_MODEL.md §1: who brought the record onto the platform."""

    HOSPITAL_UPLOAD = "HOSPITAL_UPLOAD"
    PATIENT_LOCKER = "PATIENT_LOCKER"


class RecordProcessingStatus(StrEnum):
    """ADR-008 pipeline states, written by the upload-indexing worker
    (records/upload_indexing.py). INDEXED: a text-layer PDF whose text joined AI retrieval.
    FAILED: a PDF with no readable text (scanned, encrypted, unparseable) or storage still
    failing on the last attempt. Images stay UPLOADED — there is no OCR. PROCESSING is
    reserved; the worker commits in one transaction, so it is never observable."""

    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"


class Hospital(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A care organization (docs/DOMAIN_MODEL.md §1). ``hid`` (``HID-XXXX``) is the
    display/business identifier — never a foreign-key target (UUIDs only, rule 4).
    The three simulated hospitals are ordinary rows, not special cases.
    """

    __tablename__ = "hospitals"

    hid: Mapped[str] = mapped_column(String(8), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[str | None] = mapped_column(String(255))
    verification_status: Mapped[HospitalVerificationStatus] = mapped_column(
        Enum(
            HospitalVerificationStatus,
            name="hospital_verification_status",
            native_enum=False,
            length=20,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=HospitalVerificationStatus.PENDING,
    )
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RecordCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Controlled vocabulary for record categorization and per-category consent."""

    __tablename__ = "record_categories"

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)


class Doctor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A clinician (FHIR Practitioner): 1:1 with an auth User, affiliated to exactly one
    Hospital in MVP (docs/DOMAIN_MODEL.md §1; multi-affiliation is future scope).
    """

    __tablename__ = "doctors"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id"), unique=True, nullable=False
    )
    hospital_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("hospitals.id"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    specialty: Mapped[str | None] = mapped_column(String(80))
    # Medical-council registration — a credential string, verified by the hospital admin
    # out of band (ADR-015); uniqueness is not enforced (formats vary by council).
    registration_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[DoctorStatus] = mapped_column(
        Enum(
            DoctorStatus,
            name="doctor_status",
            native_enum=False,
            length=20,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=DoctorStatus.PENDING,
    )


class HospitalAdmin(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The hospital-admin membership profile (docs/DOMAIN_MODEL.md §1: a User is linked
    1:1 to exactly one profile entity matching its role).
    """

    __tablename__ = "hospital_admins"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id"), unique=True, nullable=False
    )
    hospital_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("hospitals.id"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)


class MedicalRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Metadata for one clinical document (FHIR DocumentReference, docs/DOMAIN_MODEL.md §1).

    Belongs to exactly one Patient — never to a hospital (cardinal rule 1); the uploading
    hospital/doctor are provenance, and the basis of the hospital's *own-upload* read
    access (ADR-013 layer 2). The object-storage key contains only UUIDs — no names, no
    filenames (docs/SECURITY.md: metadata can leak). ``is_hidden`` is the patient-controlled
    visibility flag, writable by the owning patient on **any** record they own regardless of
    origin (docs/DOMAIN_MODEL.md §3) — the read layers already treat every record alike, so
    gating the write by origin would give one flag two rules.
    """

    __tablename__ = "medical_records"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("patients.id"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("record_categories.id"), nullable=False
    )
    origin: Mapped[RecordOrigin] = mapped_column(
        Enum(
            RecordOrigin,
            name="record_origin",
            native_enum=False,
            length=20,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    uploaded_by_hospital_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("hospitals.id"), index=True
    )
    # Set when a doctor uploads (prescriptions, M3+ — requires an active consent grant).
    uploaded_by_doctor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("doctors.id")
    )
    date_of_service: Mapped[date] = mapped_column(Date(), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    processing_status: Mapped[RecordProcessingStatus] = mapped_column(
        Enum(
            RecordProcessingStatus,
            name="record_processing_status",
            native_enum=False,
            length=20,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=RecordProcessingStatus.UPLOADED,
    )
    is_hidden: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)


class HospitalAuditLog(UUIDPrimaryKeyMixin, Base):
    """Append-only audit trail for administrative hospital verification lifecycle events (ADR-034).

    Written in the same database transaction as the hospital status transition. No update/delete
    API exists; rows are immutable evidence.
    """

    __tablename__ = "hospital_audit_logs"

    hospital_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("hospitals.id"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("users.id"), nullable=False)
    action: Mapped[HospitalLifecycleAction] = mapped_column(
        Enum(
            HospitalLifecycleAction,
            name="hospital_lifecycle_action",
            native_enum=False,
            length=20,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "action IN ('VERIFIED', 'REJECTED', 'SUSPENDED', 'REINSTATED')",
            name="action_valid",
        ),
        Index(
            "ix_hospital_audit_logs_hospital_id_occurred_at_id",
            "hospital_id",
            text("occurred_at DESC"),
            text("id DESC"),
        ),
    )
