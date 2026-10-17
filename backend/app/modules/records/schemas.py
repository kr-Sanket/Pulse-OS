"""records API schemas — camelCase wire shapes (docs/API_GUIDELINES.md).

Upload requests arrive as multipart form fields (not JSON), so they are declared in the
router with ``Form(...)``; the models here are the JSON bodies and all responses.
"""

from datetime import UTC, date, datetime
from uuid import UUID

from pydantic import Field, StrictBool, field_validator

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
    verified_by_user_id: UUID | None = None
    verified_at: datetime | None = None

    @field_validator("verified_at", mode="after")
    @classmethod
    def _ensure_utc(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v


class HospitalListResponse(ApiModel):
    items: list[HospitalResponse]


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


# -- records: requests -------------------------------------------------------------------


class RecordVisibilityUpdateRequest(RequestModel):
    """The patient's disclosure preference for one record they own.

    One field, required and non-nullable, which is what keeps this model free of the
    partial-update machinery ``PatientProfileUpdateRequest`` needs. There is no "leave
    alone" to express (the caller states the state they want) and no "clear" (the column is
    NOT NULL), so an omitted key, an explicit ``null`` and a non-boolean are all simply
    invalid — 422 by the field's own declaration rather than by a validator.

    The record is named by the path and the patient by the token, so neither appears here.
    ``RequestModel`` forbids unknown fields, which makes naming one a 422 rather than a
    silently ignored key — a caller that believes it moved a record to another patient must
    be told otherwise.

    ``StrictBool`` rather than ``bool``, which is a deliberate departure from Pydantic's
    default coercion: in lax mode ``"yes"``, ``"on"`` and ``1`` all become ``True`` and
    ``"no"`` becomes ``False``. Guessing is the wrong behaviour for a disclosure control —
    a client that sends the wrong type should be corrected, not have a privacy setting
    inferred on its behalf. JSON has a native boolean, so nothing legitimate needs the
    coercion. (Dates elsewhere in the API do need it; JSON has no date.)
    """

    is_hidden: StrictBool


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
    """One record as a caller entitled to the whole of it sees it.

    ``isHidden`` is the patient's own disclosure preference. It is carried here rather than
    on a patient-only model because a grantee never receives this response for a hidden
    record at all — the read is refused before serialisation — so for a doctor the field is
    false by construction. The uploading hospital does see it on its own upload, which is
    true and worth its knowing: the record it filed is no longer being shared onward.
    ``GrantedRecordResponse`` deliberately does **not** gain the field; a value that can only
    ever be false would be dead weight on an allow-list whose point is narrowness.
    """

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
    is_hidden: bool
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
            is_hidden=view.record.is_hidden,
            uploaded_by_hospital=hospital,
            created_at=view.record.created_at,
        )


class RecordListResponse(ApiModel):
    items: list[RecordMetadataResponse]
    next_cursor: str | None


class GrantedRecordResponse(ApiModel):
    """One record as its *grantee* sees it before opening it (ADR-020).

    A separate model from ``RecordMetadataResponse``, not a subset of it, and that is the
    point: reuse would mean every field ever added for a patient's own view becomes visible
    to clinicians with no review step. What a doctor may see here is an allow-list, and
    widening it has to be a deliberate edit to this class.

    Enough to *choose* a record — which category, when the care happened, who issued it,
    whether it came from a hospital or the patient's own locker — and nothing that describes
    the document itself. Three fields are withheld on purpose:

    - ``originalFilename``: user-supplied text that routinely carries a diagnosis
      ("hiv-panel-positive.pdf"). The upload path already refuses to put it in the storage
      key for exactly this reason (see ``RecordService._store``); a field unsafe to place in
      an object key is unsafe to broadcast across a page. It is disclosed at download time,
      where it is needed and where a single authorized read has already been audited.
    - ``description``: free text with no vocabulary, able to say far more about a patient
      than the category the grant was given for.
    - ``sizeBytes`` / ``contentType`` / ``processingStatus``: a page-count proxy, an icon,
      and an M5 pipeline state — none of them help a clinician pick a document.

    All of them remain available on ``GET /records/{id}``, which authorizes and audits that
    disclosure one record at a time. The listing's job is to choose; the read's job is to
    disclose.
    """

    id: UUID
    category_code: str
    category_display_name: str
    origin: RecordOrigin
    date_of_service: date
    uploaded_by_hospital: UploadingHospitalResponse | None
    created_at: datetime

    @classmethod
    def from_view(cls, view: RecordView) -> "GrantedRecordResponse":
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
            uploaded_by_hospital=hospital,
            created_at=view.record.created_at,
        )


class GrantedRecordListResponse(ApiModel):
    """A page of consented records, plus the scope that produced it.

    ``grantedCategories`` is what makes an empty ``items`` readable: with a live grant it
    means the patient holds nothing in what was approved, without one it means nothing was
    approved. It also answers a question no other endpoint does — a clinician can see that
    a request was ``DECIDED`` but not which categories survived it — so it is the scope, not
    a convenience.
    """

    patient_id: UUID
    granted_categories: list[RecordCategoryResponse]
    items: list[GrantedRecordResponse]
    next_cursor: str | None


class DownloadUrlResponse(ApiModel):
    url: str
    expires_in_seconds: int
