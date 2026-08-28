"""Records API schemas — camelCase wire shapes (docs/API_GUIDELINES.md)."""

from datetime import date, datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.modules.records.models import ProcessingStatus, RecordOrigin
from app.shared.schemas import ApiModel, RequestModel


class RecordCategoryCreate(RequestModel):
    code: str = Field(min_length=1, max_length=50)
    display_name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("code", "display_name")
    @classmethod
    def _strip_and_require_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class RecordCategoryRead(ApiModel):
    id: UUID
    code: str
    display_name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class MedicalRecordCreate(RequestModel):
    patient_id: UUID
    category_id: UUID
    origin: RecordOrigin
    hospital_id: UUID | None = None
    doctor_id: UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    service_date: date | None = None
    s3_key: str = Field(min_length=1, max_length=500)
    file_name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=100)
    file_size_bytes: int | None = Field(default=None, ge=0)

    @field_validator("title", "s3_key", "file_name", "mime_type")
    @classmethod
    def _strip_and_require_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class MedicalRecordRead(ApiModel):
    id: UUID
    patient_id: UUID
    category_id: UUID
    origin: RecordOrigin
    hospital_id: UUID | None
    doctor_id: UUID | None
    title: str
    service_date: date | None
    s3_key: str
    file_name: str
    mime_type: str
    file_size_bytes: int | None
    processing_status: ProcessingStatus
    failure_reason: str | None
    is_hidden: bool
    created_at: datetime
    updated_at: datetime


class CategoryExistenceSummary(ApiModel):
    """Category-level existence projection (docs/DATABASE_DESIGN.md §Modeling Rules).
    Doctors without active consent can see ONLY that categories exist at organizations,
    with zero exposure of filenames, dates, titles, or clinical metadata.
    """

    category_id: UUID
    category_code: str
    category_name: str
    hospital_id: UUID | None
    record_count: int
