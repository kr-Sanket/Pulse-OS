"""Patients domain service: registration (idempotent), Health ID issuance, profile read.

Framework-free; owns no transaction — the request scope commits (app/core/db.py). Claims
are provisioned inside the same request transaction, so a provider failure rolls back the
user/patient rows and a retry starts clean.
"""

from collections.abc import Callable, Mapping
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
    RegistrationConflictError,
)
from app.modules.patients.health_id import generate_health_id
from app.modules.patients.models import Gender, Patient
from app.modules.patients.repository import PatientRepository

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
                phone=_claim_string(identity.claims, "phone_number", max_length=20),
                email=_claim_string(identity.claims, "email", max_length=255),
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

    async def get_patient_by_id(self, id: UUID) -> Patient | None:
        return await self._patients.get_by_id(id)

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


def _claim_string(claims: Mapping[str, object], key: str, *, max_length: int) -> str | None:
    """Verified contact points from the token (docs/DOMAIN_MODEL.md: User carries them);
    anything unexpected is dropped rather than trusted."""
    value = claims.get(key)
    if isinstance(value, str) and 0 < len(value) <= max_length:
        return value
    return None
