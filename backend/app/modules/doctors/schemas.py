"""Doctors API schemas — camelCase wire shapes (docs/API_GUIDELINES.md)."""

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.shared.schemas import ApiModel, RequestModel


class DoctorCreate(RequestModel):
    hospital_id: UUID
    full_name: str = Field(min_length=1, max_length=120)
    registration_number: str = Field(min_length=1, max_length=50)
    specialty: str = Field(min_length=1, max_length=100)

    @field_validator("full_name", "registration_number", "specialty")
    @classmethod
    def _strip_and_require_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class DoctorRead(ApiModel):
    id: UUID
    user_id: UUID
    hospital_id: UUID
    full_name: str
    registration_number: str
    specialty: str
    created_at: datetime
    updated_at: datetime
