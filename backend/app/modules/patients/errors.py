"""Patients domain exceptions. HTTP translation happens in the router layer only."""


class PatientsError(Exception):
    """Base class for patients-module domain errors."""


class DuplicateHealthIdError(PatientsError):
    """A drawn Health ID candidate collided with an existing one — redraw (ADR-012)."""


class DuplicatePatientError(PatientsError):
    """A patient row for this user already exists (lost a concurrent-registration race)."""


class RegistrationConflictError(PatientsError):
    """Registration cannot proceed for this account. ``detail`` is safe for clients."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class HealthIdAllocationError(PatientsError):
    """All Health ID draws collided — statistically impossible outside of a bug."""


class InvalidHealthIdError(PatientsError):
    """The candidate is not a well-formed Pulse Health ID (shape or ISO 7064 check
    character, ADR-012). Distinct from "no such patient": a transposed character fails
    here, which is exactly the offline typo detection the check character exists for."""


class PatientNotFoundError(PatientsError):
    """A well-formed Health ID that matches no patient."""
