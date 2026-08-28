"""doctors-owned tables (docs/DOMAIN_MODEL.md §1: Doctor, FHIR Practitioner-aligned).

``user_id`` is a plain FK to auth's ``users`` table (1:1 with User, role=DOCTOR).
``hospital_id`` is an internal UUID FK to ``hospitals`` (N:1 affiliation in MVP).
"""

import uuid

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Doctor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A clinician. 1:1 with User, affiliated with exactly one Hospital in MVP.
    Requests access, reads granted records, uploads prescriptions.
    """

    __tablename__ = "doctors"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id"), unique=True, nullable=False
    )
    hospital_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("hospitals.id"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    registration_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    specialty: Mapped[str] = mapped_column(String(100), nullable=False)
