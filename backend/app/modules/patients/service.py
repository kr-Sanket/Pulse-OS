"""Patients domain service: registration (idempotent), Health ID issuance, profile read.

Framework-free; owns no transaction — the request scope commits (app/core/db.py). Claims
are provisioned inside the same request transaction, so a provider failure rolls back the
user/patient rows and a retry starts clean.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.modules.auth.accounts import UserAccountService
from app.modules.auth.domain import Role
from app.modules.auth.errors import DuplicateUserError
from app.modules.auth.models import User
from app.modules.auth.provider import VerifiedToken
from app.modules.patients.errors import (
    DuplicateHealthIdError,
    DuplicatePatientError,
    HealthIdAllocationError,
    InvalidHealthIdError,
    PatientNotFoundError,
    RegistrationConflictError,
)
from app.modules.patients.health_id import generate_health_id, is_valid_health_id
from app.modules.patients.models import Gender, Patient
from app.modules.patients.repository import PatientRepository
from app.modules.patients.schemas import UNSET, Unset

# 32^6 candidates per year — even a handful of retries means something is broken.
_MAX_HEALTH_ID_ATTEMPTS = 8


@dataclass(frozen=True, slots=True)
class RegistrationOutcome:
    patient: Patient
    created: bool


class PatientService:
    def __init__(
        self,
        accounts: UserAccountService,
        patients: PatientRepository,
        health_id_factory: Callable[[], str] = generate_health_id,
    ) -> None:
        self._accounts = accounts
        self._patients = patients
        self._health_id_factory = health_id_factory

    async def register(
        self,
        identity: VerifiedToken,
        *,
        full_name: str,
        date_of_birth: date | None,
        gender: Gender | None,
    ) -> RegistrationOutcome:
        """Idempotent registration: a repeated call returns the existing profile (and
        re-provisions claims, healing a failed earlier attempt) instead of duplicating."""
        existing = await self._accounts.get_by_firebase_uid(identity.firebase_uid)
        if existing is not None:
            return await self._complete_existing(existing)

        try:
            user = await self._accounts.create_user(
                firebase_uid=identity.firebase_uid,
                role=Role.PATIENT,
                phone=identity.string_claim("phone_number", max_length=20),
                email=identity.string_claim("email", max_length=255),
            )
            patient = await self._create_patient_with_health_id(
                user.id, full_name=full_name, date_of_birth=date_of_birth, gender=gender
            )
        except (DuplicateUserError, DuplicatePatientError):
            # Lost a concurrent-registration race — fall through to the idempotent path.
            racer = await self._accounts.get_by_firebase_uid(identity.firebase_uid)
            if racer is None:
                raise RegistrationConflictError(
                    "Registration could not be completed; please retry."
                ) from None
            return await self._complete_existing(racer)

        await self._accounts.provision_claims(
            identity.firebase_uid, role=Role.PATIENT, user_id=user.id
        )
        return RegistrationOutcome(patient=patient, created=True)

    async def get_profile(self, user_id: UUID) -> Patient | None:
        return await self._patients.get_by_user_id(user_id)

    async def update_profile(
        self,
        user_id: UUID,
        *,
        full_name: str | Unset = UNSET,
        date_of_birth: date | None | Unset = UNSET,
        gender: Gender | None | Unset = UNSET,
    ) -> Patient:
        """Change the caller's own profile. Partial: an omitted field is left alone.

        **Ownership is the signature, not a check.** The row is resolved from the
        authenticated ``user_id`` and there is no parameter naming a patient, so editing
        somebody else's profile is not expressible — the same shape ``get_profile`` uses.

        Three fields, and the sentinel is what makes that safe: ``health_id``,
        ``user_id`` and the timestamps are simply never assigned here, so no request shape
        can reach them. ``UNSET`` distinguishes "not mentioned" from an explicit ``null``,
        which for the two nullable columns is a real instruction to clear them.

        ``updated_at`` advances by way of TimestampMixin's ``onupdate``; nothing here sets
        a timestamp, and nothing here writes an audit event — a profile edit is not access
        to a record, and ``AuditAction`` has no member that would state it truthfully.
        """
        patient = await self._patients.get_by_user_id(user_id)
        if patient is None:
            raise PatientNotFoundError()
        if not isinstance(full_name, Unset):
            patient.full_name = full_name
        if not isinstance(date_of_birth, Unset):
            patient.date_of_birth = date_of_birth
        if not isinstance(gender, Unset):
            patient.gender = gender
        return await self._patients.update(patient)

    async def lookup_by_health_id(self, health_id: str) -> Patient:
        """Resolve a Health ID to the patient it identifies, for identity confirmation.

        The safety step in front of a hospital upload: a record is filed against a Health
        ID and no endpoint can move or delete it afterwards, so the uploader has to be able
        to check whose history they are about to write to before they write to it.

        **Validated before it is queried, and that ordering is the point.** ADR-012 gave the
        Health ID an ISO 7064 check character precisely so a transposed or mistyped
        character is detectable without a database, and this is the reception desk it was
        designed for. Running the check first means a typo is reported as a malformed ID
        rather than as "no such patient" — the difference between "you typed it wrong" and
        "this person is not on PulseOS", which are different instructions to the person at
        the desk.

        Case-insensitive and whitespace-tolerant on input (ADR-012 stores canonical
        uppercase); the row's own Health ID is what comes back, so the caller is shown the
        canonical form rather than whatever they typed.

        Authorization is the caller's concern, not this method's: it says who a Health ID
        belongs to and nothing about what anyone may do with them. The record write that
        follows is authorized independently by the records module.
        """
        candidate = health_id.strip().upper()
        if not is_valid_health_id(candidate):
            raise InvalidHealthIdError()
        patient = await self._patients.get_by_health_id(candidate)
        if patient is None:
            raise PatientNotFoundError()
        return patient

    async def _complete_existing(self, user: User) -> RegistrationOutcome:
        if user.role is not Role.PATIENT:
            raise RegistrationConflictError("Account is already registered with a different role.")
        patient = await self._patients.get_by_user_id(user.id)
        if patient is None:
            # Unreachable while registration is atomic; guarded so it can never 500 into
            # a duplicate-creation path.
            raise RegistrationConflictError("Account is in an inconsistent registration state.")
        await self._accounts.provision_claims(user.firebase_uid, role=user.role, user_id=user.id)
        return RegistrationOutcome(patient=patient, created=False)

    async def _create_patient_with_health_id(
        self, user_id: UUID, *, full_name: str, date_of_birth: date | None, gender: Gender | None
    ) -> Patient:
        # Draw-and-insert (ADR-012): the DB unique constraint is the collision check.
        for _ in range(_MAX_HEALTH_ID_ATTEMPTS):
            candidate = Patient(
                user_id=user_id,
                health_id=self._health_id_factory(),
                full_name=full_name,
                date_of_birth=date_of_birth,
                gender=gender,
            )
            try:
                return await self._patients.add(candidate)
            except DuplicateHealthIdError:
                continue
        raise HealthIdAllocationError()
