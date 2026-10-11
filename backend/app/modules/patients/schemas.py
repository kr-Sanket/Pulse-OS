"""Patients API schemas — camelCase wire shapes (docs/API_GUIDELINES.md)."""

from datetime import date, datetime
from enum import Enum
from typing import Final

from pydantic import Field, field_validator, model_validator

from app.modules.patients.models import Gender
from app.shared.schemas import ApiModel, RequestModel


def _require_content(value: str | None) -> str | None:
    """A name of nothing but spaces is not a name. Shared by registration and editing so a
    value that could not be registered cannot be reached by editing either."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be blank")
    return stripped


def _require_past(value: date | None) -> date | None:
    if value is not None and value >= date.today():
        raise ValueError("must be in the past")
    return value


class PatientRegistrationRequest(RequestModel):
    full_name: str = Field(min_length=1, max_length=120)
    date_of_birth: date | None = None
    gender: Gender | None = None

    @field_validator("full_name")
    @classmethod
    def _strip_and_require_content(cls, value: str) -> str:
        # The shared helper is nullable-tolerant for the update model; registration's own
        # field is required, so the None branch is unreachable here.
        stripped = _require_content(value)
        assert stripped is not None
        return stripped

    @field_validator("date_of_birth")
    @classmethod
    def _must_be_in_the_past(cls, value: date | None) -> date | None:
        return _require_past(value)


class Unset(Enum):
    """The absence of a field in a PATCH body, as a value.

    ``None`` cannot carry this meaning here: ``dateOfBirth`` and ``gender`` are nullable
    columns, so an explicit ``null`` is a real instruction — *clear this* — and must be
    distinguishable from *leave it alone*. One sentinel expresses that difference all the
    way down to the service, so no layer has to consult a set of field names to know what
    the caller actually asked for.
    """

    TOKEN = "unset"


UNSET: Final = Unset.TOKEN


class PatientProfileUpdateRequest(RequestModel):
    """A partial update of the caller's own profile.

    Three fields, and deliberately only three: they are the whole of what ``patients``
    stores about a person beyond their identity. ``healthId``, ``firebaseUid``, ``role``,
    ``status`` and ``createdAt`` are not omitted from this model as an oversight to be
    tolerated — ``RequestModel`` forbids unknown fields, so naming one is a 422 rather than
    a silently ignored key. That is the enforcement; this docstring is only the reason.

    Validation is not restated here. ``PatientRegistrationRequest``'s rules are reused
    outright, because a name that could not be registered must not be reachable by editing.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    date_of_birth: date | None = None
    gender: Gender | None = None

    @field_validator("full_name")
    @classmethod
    def _strip_and_require_content(cls, value: str | None) -> str | None:
        return _require_content(value)

    @field_validator("date_of_birth")
    @classmethod
    def _must_be_in_the_past(cls, value: date | None) -> date | None:
        return _require_past(value)

    @model_validator(mode="after")
    def _reject_an_empty_body(self) -> "PatientProfileUpdateRequest":
        """A PATCH that names no field is a mistake, not a no-op: answering 200 would tell
        the caller their edit was applied."""
        if not self.model_fields_set:
            raise ValueError("provide at least one field to update")
        return self

    @model_validator(mode="after")
    def _reject_a_null_name(self) -> "PatientProfileUpdateRequest":
        """``full_name`` is NOT NULL in the schema, so clearing it is not an operation the
        column can express. Refused here rather than at the database, where it would be a
        500 instead of a 422."""
        if "full_name" in self.model_fields_set and self.full_name is None:
            raise ValueError("fullName must not be null")
        return self

    def full_name_change(self) -> str | Unset:
        if "full_name" not in self.model_fields_set:
            return UNSET
        # ``_reject_a_null_name`` has already refused an explicit null, so a field that is
        # set is a value. The assertion states that to the type checker rather than
        # widening the service's signature to accept a None it must never be given.
        assert self.full_name is not None
        return self.full_name

    def date_of_birth_change(self) -> date | Unset | None:
        return self.date_of_birth if "date_of_birth" in self.model_fields_set else UNSET

    def gender_change(self) -> Gender | Unset | None:
        return self.gender if "gender" in self.model_fields_set else UNSET


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
