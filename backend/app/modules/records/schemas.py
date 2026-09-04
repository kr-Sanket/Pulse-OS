"""records API schemas — camelCase wire shapes (docs/API_GUIDELINES.md).

Upload requests arrive as multipart form fields (not JSON), so they are declared in the
router with ``Form(...)``; the models here are the JSON bodies and all responses.
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.modules.records.models import (
    Doctor,
    DoctorStatus,
    Hospital,
    HospitalAdmin,
    HospitalVerificationStatus,
    RecordOrigin,
    RecordProcessingStatus,
)
from app.modules.records.service import RecordView
from app.shared.schemas import ApiModel, RequestModel


def _stripped_non_blank(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be blank")
    return stripped


# -- organizations: requests ---------------------------------------------------------


class HospitalRegistrationRequest(RequestModel):
    hospital_name: str = Field(min_length=1, max_length=120)
    hospital_address: str | None = Field(default=None, max_length=255)
    admin_full_name: str = Field(min_length=1, max_length=120)

    _strip_name = field_validator("hospital_name", "admin_full_name")(_stripped_non_blank)


class DoctorRegistrationRequest(RequestModel):
    full_name: str = Field(min_length=1, max_length=120)
    specialty: str | None = Field(default=None, max_length=80)
    registration_number: str = Field(min_length=1, max_length=40)
    hospital_hid: str = Field(min_length=1, max_length=8)

    _strip_fields = field_validator("full_name", "registration_number", "hospital_hid")(
        _stripped_non_blank
    )


# -- organizations: responses --------------------------------------------------------


class HospitalResponse(ApiModel):
    hid: str
    name: str
    address: str | None
    verification_status: HospitalVerificationStatus
    created_at: datetime


class HospitalAdminProfileResponse(ApiModel):
    """A hospital admin's view of their own hospital (registration + GET /hospitals/me)."""

    hospital: HospitalResponse
    admin_full_name: str

    @classmethod
    def build(cls, hospital: Hospital, admin: HospitalAdmin) -> "HospitalAdminProfileResponse":
        return cls(
            hospital=HospitalResponse.model_validate(hospital),
            admin_full_name=admin.full_name,
        )


class DoctorResponse(ApiModel):
    """A doctor as seen by their hospital admin (and by themselves)."""

    id: UUID
    full_name: str
    specialty: str | None
    registration_number: str
    status: DoctorStatus
    created_at: datetime


class DoctorProfileResponse(ApiModel):
    """A doctor's own profile, with their hospital context."""

    full_name: str
    specialty: str | None
    registration_number: str
    status: DoctorStatus
    hospital: HospitalResponse
    created_at: datetime

    @classmethod
    def build(cls, doctor: Doctor, hospital: Hospital) -> "DoctorProfileResponse":
        return cls(
            full_name=doctor.full_name,
            specialty=doctor.specialty,
            registration_number=doctor.registration_number,
            status=doctor.status,
            hospital=HospitalResponse.model_validate(hospital),
            created_at=doctor.created_at,
        )


class DoctorListResponse(ApiModel):
    items: list[DoctorResponse]
    next_cursor: str | None


# -- records: responses ----------------------------------------------------------------


class RecordCategoryResponse(ApiModel):
    code: str
    display_name: str


class RecordCategoryListResponse(ApiModel):
    items: list[RecordCategoryResponse]


class RecordExistenceResponse(ApiModel):
    """Which categories a patient holds records in — the clinician's discovery view.

    Deliberately the *same item shape* as the category vocabulary and nothing more: a code
    and a display name. No id, no filename, no hospital, no size, no service date, no
    description, and no count — a count is itself clinical signal (three MRIs and thirty
    are different stories), so this first cut answers presence only. A distinct response
    model rather than a reused one because the two operations mean different things: one
    publishes the vocabulary, this one says what a named patient has.
    """

    items: list[RecordCategoryResponse]


class UploadingHospitalResponse(ApiModel):
    hid: str
    name: str


class RecordMetadataResponse(ApiModel):
    id: UUID
    category_code: str
    category_display_name: str
    origin: RecordOrigin
    date_of_service: date
    description: str | None
    original_filename: str
    content_type: str
    size_bytes: int
    processing_status: RecordProcessingStatus
    uploaded_by_hospital: UploadingHospitalResponse | None
    created_at: datetime

    @classmethod
    def from_view(cls, view: RecordView) -> "RecordMetadataResponse":
        hospital = (
            UploadingHospitalResponse(hid=view.hospital.hid, name=view.hospital.name)
            if view.hospital is not None
            else None
        )
        return cls(
            id=view.record.id,
            category_code=view.category.code,
            category_display_name=view.category.display_name,
            origin=view.record.origin,
            date_of_service=view.record.date_of_service,
            description=view.record.description,
            original_filename=view.record.original_filename,
            content_type=view.record.content_type,
            size_bytes=view.record.size_bytes,
            processing_status=view.record.processing_status,
            uploaded_by_hospital=hospital,
            created_at=view.record.created_at,
        )


class RecordListResponse(ApiModel):
    items: list[RecordMetadataResponse]
    next_cursor: str | None


class DownloadUrlResponse(ApiModel):
    url: str
    expires_in_seconds: int
