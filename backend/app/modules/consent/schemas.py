"""Consent API schemas — camelCase wire shapes (docs/API_GUIDELINES.md)."""

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.modules.consent.models import DecisionType, RequestStatus
from app.shared.schemas import ApiModel, RequestModel


class AccessRequestCreate(RequestModel):
    patient_id: UUID
    purpose: str = Field(min_length=1, max_length=500)
    category_ids: list[UUID] = Field(min_length=1)

    @field_validator("purpose")
    @classmethod
    def _strip_and_require_purpose(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class AccessRequestRead(ApiModel):
    id: UUID
    patient_id: UUID
    doctor_id: UUID
    hospital_id: UUID
    purpose: str
    status: RequestStatus
    expires_at: datetime
    category_ids: list[UUID]
    created_at: datetime
    updated_at: datetime


class CategoryDecisionItem(RequestModel):
    category_id: UUID
    decision: DecisionType
    expires_at: datetime | None = None


class ConsentDecisionRequest(RequestModel):
    decisions: list[CategoryDecisionItem] = Field(min_length=1)


class ConsentDecisionRead(ApiModel):
    id: UUID
    request_id: UUID
    patient_id: UUID
    doctor_id: UUID
    category_id: UUID
    decision: DecisionType
    decided_at: datetime


class ConsentGrantRead(ApiModel):
    id: UUID
    patient_id: UUID
    doctor_id: UUID
    category_id: UUID
    decision_id: UUID | None
    granted_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    is_active: bool
