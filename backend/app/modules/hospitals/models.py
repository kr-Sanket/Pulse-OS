"""hospitals-owned tables (docs/DOMAIN_MODEL.md §1: Hospital, FHIR Organization-aligned).

``hospital_id`` is the unique business identifier (e.g. HID-0001 per PROJECT_OVERVIEW.md);
internal foreign keys use the UUID primary key (docs/DATABASE_DESIGN.md principle 6).
"""

from enum import StrEnum

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class HospitalStatus(StrEnum):
    """Verification status set by System Admin (docs/DOMAIN_MODEL.md §1)."""

    PENDING = "PENDING"
    VERIFIED = "VERIFIED"


class Hospital(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A care organization. UUID is the internal identity; hospital_id (HID-XXXX)
    is a unique business identifier, never a foreign key target.
    """

    __tablename__ = "hospitals"

    hospital_id: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[HospitalStatus] = mapped_column(
        Enum(
            HospitalStatus,
            name="hospital_status",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=HospitalStatus.PENDING,
    )
