"""Hospitals API schemas — camelCase wire shapes (docs/API_GUIDELINES.md)."""

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.modules.hospitals.models import HospitalStatus
from app.shared.schemas import ApiModel, RequestModel


class HospitalCreate(RequestModel):
    hospital_id: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    status: HospitalStatus = HospitalStatus.PENDING

    @field_validator("hospital_id", "name")
    @classmethod
    def _strip_and_require_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("address")
    @classmethod
    def _strip_optional_address(cls, value: str | None) -> str | None:
        if value is not None:
            stripped = value.strip()
            return stripped if stripped else None
        return None


class HospitalRead(ApiModel):
    id: UUID
    hospital_id: str
    name: str
    address: str | None
    status: HospitalStatus
    created_at: datetime
    updated_at: datetime
