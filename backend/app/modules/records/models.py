"""records-owned reference tables (M0.3 seed scope — the MedicalRecord itself is M2).

``Hospital`` (FHIR Organization) lives here because the conceptual entity map
(docs/DATABASE_DESIGN.md) hangs both DocumentReference and Practitioner off the
Organization, and ROADMAP M2 bundles hospitals with the records milestone; if doctor
management motivates different ownership at M2, moving it is a reviewed follow-up.
``RecordCategory`` is the consent granularity unit — a seedable table, NOT a code enum,
so adding a category never requires a logic migration (docs/DOMAIN_MODEL.md §1).
"""

from enum import StrEnum

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class HospitalVerificationStatus(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"


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
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=HospitalVerificationStatus.PENDING,
    )


class RecordCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Controlled vocabulary for record categorization and per-category consent."""

    __tablename__ = "record_categories"

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
