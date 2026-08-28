"""patients-owned tables (docs/DOMAIN_MODEL.md §1: Patient, FHIR Patient-aligned).

``user_id`` is a plain FK to auth's ``users`` table — referential integrity only; no ORM
relationship crosses the module boundary (docs/SYSTEM_ARCHITECTURE.md isolation rule 1).
The FHIR-style external-identifiers list (ABHA later) is deliberately absent until an
external system exists — the Health ID column plus UUID FKs make it purely additive.
"""

import uuid
from datetime import date
from enum import StrEnum

from sqlalchemy import Date, Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Gender(StrEnum):
    """FHIR administrative-gender vocabulary, SCREAMING_SNAKE per API_GUIDELINES."""

    MALE = "MALE"
    FEMALE = "FEMALE"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class Patient(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The data owner. UUID is the internal identity; the Health ID (ADR-012) is a unique
    business identifier, never a foreign key target.
    """

    __tablename__ = "patients"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id"), unique=True, nullable=False
    )
    health_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date())
    gender: Mapped[Gender | None] = mapped_column(
        Enum(
            Gender,
            name="patient_gender",
            native_enum=False,
            length=10,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        )
    )
