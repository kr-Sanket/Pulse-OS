"""consent-owned tables (docs/DOMAIN_MODEL.md §1: AccessRequest, ConsentDecision, ConsentGrant).

FHIR Consent-aligned metadata. Granular by RecordCategory (docs/DATABASE_DESIGN.md).
Immutable decision history + fast O(1) active grant enforcement (ADR-013).
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RequestStatus(StrEnum):
    """Lifecycle status of an access request (docs/DOMAIN_MODEL.md §1)."""

    PENDING = "PENDING"
    DECIDED = "DECIDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class DecisionType(StrEnum):
    """Immutable patient decision per category (docs/DOMAIN_MODEL.md §1)."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AccessRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A Doctor's petition to see a Patient's records across a set of categories.
    Expires if undecided (design default: 7 days).
    """

    __tablename__ = "access_requests"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("patients.id"), nullable=False, index=True
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("doctors.id"), nullable=False, index=True
    )
    hospital_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("hospitals.id"), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[RequestStatus] = mapped_column(
        Enum(
            RequestStatus,
            name="request_status",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=RequestStatus.PENDING,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccessRequestCategory(UUIDPrimaryKeyMixin, Base):
    """Requested record categories associated with an AccessRequest."""

    __tablename__ = "access_request_categories"
    __table_args__ = (
        UniqueConstraint(
            "request_id", "category_id", name="uq_access_request_categories_request_id_category_id"
        ),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("access_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("record_categories.id"), nullable=False, index=True
    )


class ConsentDecision(UUIDPrimaryKeyMixin, Base):
    """Immutable historical decision event.
    For (AccessRequest, category), the patient decided APPROVED or REJECTED.
    Never updated or deleted — revocation is recorded as a new state change.
    """

    __tablename__ = "consent_decisions"

    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("access_requests.id"), nullable=False, index=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("patients.id"), nullable=False, index=True
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("doctors.id"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("record_categories.id"), nullable=False, index=True
    )
    decision: Mapped[DecisionType] = mapped_column(
        Enum(
            DecisionType,
            name="decision_type",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ConsentGrant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Active permission derived from an approval decision.
    Enforcement reads grants only — O(1) check, no history traversal (ADR-013).
    Grantee is the individual doctor; scope is per-category.
    """

    __tablename__ = "consent_grants"
    __table_args__ = (
        Index(
            "ix_consent_grants_patient_doctor_category",
            "patient_id",
            "doctor_id",
            "category_id",
        ),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("patients.id"), nullable=False, index=True
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("doctors.id"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("record_categories.id"), nullable=False, index=True
    )
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("consent_decisions.id"), nullable=True, index=True
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_active(self) -> bool:
        """Helper to evaluate active status in memory against current UTC timestamp."""
        now = datetime.now(self.expires_at.tzinfo)
        return self.revoked_at is None and self.expires_at > now
