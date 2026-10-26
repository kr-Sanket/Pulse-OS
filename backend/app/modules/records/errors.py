"""records domain exceptions. HTTP translation happens in the router layer only.

Two families: organization/onboarding errors (ADR-015) and record-content errors.
``RecordNotFoundError`` deliberately covers "exists but you may not see it" — the
403-vs-404 rule (docs/API_GUIDELINES.md): callers without a relationship to a record
must not learn that it exists.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.records.models import HospitalVerificationStatus


class RecordsError(Exception):
    """Base class for records-module domain errors."""


class OrgRegistrationConflictError(RecordsError):
    """Hospital/doctor registration cannot proceed for this account.
    ``detail`` is safe for clients."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class DuplicateHidError(RecordsError):
    """A drawn HID candidate collided with an existing hospital — redraw (ADR-015)."""


class DuplicateProfileError(RecordsError):
    """A doctor/admin profile for this user already exists (concurrent-registration race)."""


class HidAllocationError(RecordsError):
    """All HID draws collided — the 10k space is effectively full or something is broken."""


class HospitalNotFoundError(RecordsError):
    """No hospital with that HID exists."""


class HospitalNotVerifiedError(RecordsError):
    """The operation requires a VERIFIED hospital (ADR-015: PENDING hospitals cannot
    take doctor registrations or upload records)."""


class InvalidHospitalStatusTransitionError(RecordsError):
    """The requested hospital verification lifecycle transition is not permitted (ADR-034)."""

    def __init__(
        self,
        current_status: "HospitalVerificationStatus",
        target_status: "HospitalVerificationStatus",
    ) -> None:
        super().__init__(
            f"Cannot transition hospital from {current_status.value} to {target_status.value}."
        )
        self.current_status = current_status
        self.target_status = target_status


class ProfileNotFoundError(RecordsError):
    """The caller's role claims exist but the matching profile row does not."""


class DoctorNotFoundError(RecordsError):
    """No such doctor in the caller's hospital (includes doctors of *other* hospitals —
    existence must not leak across hospitals)."""


class ClinicianNotActiveError(RecordsError):
    """The caller is a doctor whose profile is not ACTIVE at its hospital (ADR-015): a
    suspended clinician keeps no clinical capability, including discovering that a
    patient's records exist."""


class UnknownPatientError(RecordsError):
    """The supplied Health ID does not match any patient."""


class UnknownCategoryError(RecordsError):
    """The supplied category code is not in the controlled vocabulary."""


class RecordNotFoundError(RecordsError):
    """No such record *for this caller* (missing or outside their relationship scope)."""


class EmptyFileError(RecordsError):
    """The uploaded file contains no bytes."""


class FileTooLargeError(RecordsError):
    """The uploaded file exceeds the configured size cap."""

    def __init__(self, max_bytes: int) -> None:
        super().__init__(max_bytes)
        self.max_bytes = max_bytes


class UnsupportedFileTypeError(RecordsError):
    """The uploaded content type is not an accepted medical-document format."""

    def __init__(self, allowed: tuple[str, ...]) -> None:
        super().__init__(allowed)
        self.allowed = allowed


class StorageUnavailableError(RecordsError):
    """Object storage could not be reached or refused the operation — server-side."""


class ConsentRequiredError(RecordsError):
    """Active consent is required to export patient records."""


class InvalidExportRequestError(RecordsError):
    """The export request parameters are invalid."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class FHIRSerializationError(RecordsError):
    """Failed to parse or serialize FHIR R4 resources for export."""


class ConflictingPatientReferenceError(FHIRSerializationError):
    """A resource carries a patient reference conflicting with the target patient."""


class MalformedResourcePayloadError(FHIRSerializationError):
    """Stored resource payload is not a valid FHIR JSON document."""
