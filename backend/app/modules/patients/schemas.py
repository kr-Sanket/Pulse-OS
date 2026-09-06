"""Patients API schemas — camelCase wire shapes (docs/API_GUIDELINES.md)."""

from datetime import date, datetime

from pydantic import Field, field_validator

from app.modules.patients.models import Gender
from app.shared.schemas import ApiModel, RequestModel


class PatientRegistrationRequest(RequestModel):
    full_name: str = Field(min_length=1, max_length=120)
    date_of_birth: date | None = None
    gender: Gender | None = None

    @field_validator("full_name")
    @classmethod
    def _strip_and_require_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("date_of_birth")
    @classmethod
    def _must_be_in_the_past(cls, value: date | None) -> date | None:
        if value is not None and value >= date.today():
            raise ValueError("must be in the past")
        return value


class PatientProfileResponse(ApiModel):
    health_id: str
    full_name: str
    date_of_birth: date | None
    gender: Gender | None
    created_at: datetime


class PatientLookupResponse(ApiModel):
    """Identity confirmation for a hospital, and deliberately nothing else.

    Two fields, both already known to whoever is holding the patient's card: the Health ID
    they typed, echoed back in canonical form, and the name to read back to them. Date of
    birth, gender, contact details, the internal UUID and every record fact are absent —
    the question this answers is "is this the person in front of me", not "who is this
    person" (docs/DOMAIN_MODEL.md §3: hospital admin gets existence + name confirmation
    only). Widening it has to be a deliberate edit to this class.
    """

    health_id: str
    full_name: str
