"""Organization domain service: hospital + admin onboarding, verification, and doctor
management (ADR-015; docs/DOMAIN_MODEL.md §3 rows "Manage doctors" / "Register/verify
hospitals").

Framework-free; owns no transaction — the request scope commits (app/core/db.py). Claims
are provisioned inside the same request transaction as the rows they describe, so a
provider failure rolls everything back (the invariant established by the patients module).
"""

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.modules.auth.accounts import UserAccountService
from app.modules.auth.domain import Role
from app.modules.auth.errors import AccountSuspendedError, DuplicateUserError
from app.modules.auth.models import User, UserStatus
from app.modules.auth.provider import VerifiedToken
from app.modules.records.errors import (
    DoctorNotFoundError,
    DuplicateHidError,
    DuplicateProfileError,
    HidAllocationError,
    HospitalNotFoundError,
    HospitalNotVerifiedError,
    OrgRegistrationConflictError,
    ProfileNotFoundError,
)
from app.modules.records.models import (
    Doctor,
    DoctorStatus,
    Hospital,
    HospitalAdmin,
    HospitalVerificationStatus,
)
from app.modules.records.repository import (
    DoctorRepository,
    HospitalAdminRepository,
    HospitalRepository,
)
from app.shared.pagination import CursorKey, encode_cursor

# 10k HIDs; hospitals number in the tens, so repeated collisions mean something is broken.
_MAX_HID_ATTEMPTS = 8


def generate_hid() -> str:
    """Draw one random ``HID-XXXX`` candidate (caller handles DB uniqueness, ADR-015).

    Hospitals are public entities — ADR-012's enumeration concern does not apply, so a
    small human-friendly space beats a long opaque one here.
    """
    return f"HID-{secrets.randbelow(10_000):04d}"


@dataclass(frozen=True, slots=True)
class HospitalRegistrationOutcome:
    hospital: Hospital
    admin: HospitalAdmin
    created: bool


@dataclass(frozen=True, slots=True)
class DoctorRegistrationOutcome:
    doctor: Doctor
    hospital: Hospital
    created: bool


@dataclass(frozen=True, slots=True)
class DoctorPage:
    doctors: list[Doctor]
    next_cursor: str | None


class HospitalService:
    def __init__(
        self,
        accounts: UserAccountService,
        hospitals: HospitalRepository,
        admins: HospitalAdminRepository,
        doctors: DoctorRepository,
        hid_factory: Callable[[], str] = generate_hid,
    ) -> None:
        self._accounts = accounts
        self._hospitals = hospitals
        self._admins = admins
        self._doctors = doctors
        self._hid_factory = hid_factory

    # -- hospital + admin onboarding (ADR-015 step 1) --------------------------------

    async def register_hospital(
        self,
        identity: VerifiedToken,
        *,
        hospital_name: str,
        hospital_address: str | None,
        admin_full_name: str,
    ) -> HospitalRegistrationOutcome:
        """Register a new hospital with the caller as its admin. Idempotent: a repeated
        call returns the existing hospital/profile (and re-provisions claims)."""
        existing = await self._accounts.get_by_firebase_uid(identity.firebase_uid)
        if existing is not None:
            return await self._complete_existing_admin(existing)

        try:
            user = await self._accounts.create_user(
                firebase_uid=identity.firebase_uid,
                role=Role.HOSPITAL_ADMIN,
                phone=identity.string_claim("phone_number", max_length=20),
                email=identity.string_claim("email", max_length=255),
            )
            hospital = await self._create_hospital_with_hid(
                name=hospital_name, address=hospital_address
            )
            admin = await self._admins.add(
                HospitalAdmin(user_id=user.id, hospital_id=hospital.id, full_name=admin_full_name)
            )
        except (DuplicateUserError, DuplicateProfileError):
            racer = await self._accounts.get_by_firebase_uid(identity.firebase_uid)
            if racer is None:
                raise OrgRegistrationConflictError(
                    "Registration could not be completed; please retry."
                ) from None
            return await self._complete_existing_admin(racer)

        await self._accounts.provision_claims(
            identity.firebase_uid, role=Role.HOSPITAL_ADMIN, user_id=user.id
        )
        return HospitalRegistrationOutcome(hospital=hospital, admin=admin, created=True)

    async def verify_hospital(self, hid: str, *, verifier_user_id: UUID) -> Hospital:
        """SYSTEM_ADMIN marks a hospital VERIFIED (ADR-015 step 2).

        ADM-01: Verification attribution is recorded when transitioning from a
        non-VERIFIED state to VERIFIED.
        Idempotent: If already VERIFIED, verification metadata is preserved and
        not overwritten. Pre-verified legacy records with missing attribution
        remain untouched.
        """
        hospital = await self._hospitals.get_by_hid(hid.strip().upper())
        if hospital is None:
            raise HospitalNotFoundError()
        if hospital.verification_status != HospitalVerificationStatus.VERIFIED:
            hospital.verification_status = HospitalVerificationStatus.VERIFIED
            hospital.verified_by_user_id = verifier_user_id
            hospital.verified_at = datetime.now(UTC)
        return hospital

    async def list_hospitals(
        self,
        *,
        verification_status: HospitalVerificationStatus | None = None,
    ) -> list[Hospital]:
        """SYSTEM_ADMIN reads hospital directory / verification backlog."""
        return await self._hospitals.list_all(verification_status=verification_status)

    async def get_own_hospital(self, user_id: UUID) -> tuple[HospitalAdmin, Hospital]:
        """The caller's admin profile + hospital (ADR-013 layer 2: own hospital)."""
        admin = await self._admins.get_by_user_id(user_id)
        if admin is None:
            raise ProfileNotFoundError()
        hospital = await self._hospitals.get_by_id(admin.hospital_id)
        if hospital is None:  # FK guarantees this; guarded so it can never 500 obscurely
            raise ProfileNotFoundError()
        return admin, hospital

    # -- doctor onboarding + management (ADR-015 step 3) -----------------------------

    async def register_doctor(
        self,
        identity: VerifiedToken,
        *,
        full_name: str,
        specialty: str | None,
        registration_number: str,
        hospital_hid: str,
    ) -> DoctorRegistrationOutcome:
        """Register the caller as a PENDING doctor of a VERIFIED hospital. Idempotent."""
        existing = await self._accounts.get_by_firebase_uid(identity.firebase_uid)
        if existing is not None:
            return await self._complete_existing_doctor(existing)

        hospital = await self._hospitals.get_by_hid(hospital_hid.strip().upper())
        if hospital is None:
            raise HospitalNotFoundError()
        if hospital.verification_status is not HospitalVerificationStatus.VERIFIED:
            raise HospitalNotVerifiedError()

        try:
            user = await self._accounts.create_user(
                firebase_uid=identity.firebase_uid,
                role=Role.DOCTOR,
                phone=identity.string_claim("phone_number", max_length=20),
                email=identity.string_claim("email", max_length=255),
            )
            doctor = await self._doctors.add(
                Doctor(
                    user_id=user.id,
                    hospital_id=hospital.id,
                    full_name=full_name,
                    specialty=specialty,
                    registration_number=registration_number,
                )
            )
        except (DuplicateUserError, DuplicateProfileError):
            racer = await self._accounts.get_by_firebase_uid(identity.firebase_uid)
            if racer is None:
                raise OrgRegistrationConflictError(
                    "Registration could not be completed; please retry."
                ) from None
            return await self._complete_existing_doctor(racer)

        await self._accounts.provision_claims(
            identity.firebase_uid, role=Role.DOCTOR, user_id=user.id
        )
        return DoctorRegistrationOutcome(doctor=doctor, hospital=hospital, created=True)

    async def get_own_doctor_profile(self, user_id: UUID) -> tuple[Doctor, Hospital]:
        doctor = await self._doctors.get_by_user_id(user_id)
        if doctor is None:
            raise ProfileNotFoundError()
        hospital = await self._hospitals.get_by_id(doctor.hospital_id)
        if hospital is None:
            raise ProfileNotFoundError()
        return doctor, hospital

    async def list_own_hospital_doctors(
        self, user_id: UUID, *, after: CursorKey | None, limit: int
    ) -> DoctorPage:
        """One page of the caller's hospital's doctors (never another hospital's)."""
        admin, _ = await self.get_own_hospital(user_id)
        rows = await self._doctors.list_page_by_hospital(
            admin.hospital_id, after=after, limit=limit + 1
        )
        has_more = len(rows) > limit
        doctors = rows[:limit]
        next_cursor = (
            encode_cursor(CursorKey(created_at=doctors[-1].created_at, item_id=doctors[-1].id))
            if has_more
            else None
        )
        return DoctorPage(doctors=doctors, next_cursor=next_cursor)

    async def set_doctor_status(
        self, user_id: UUID, doctor_id: UUID, status: DoctorStatus
    ) -> Doctor:
        """Activate/deactivate a doctor of the caller's own hospital. A doctor of another
        hospital is reported exactly like a nonexistent one (404-not-403 rule)."""
        admin, _ = await self.get_own_hospital(user_id)
        doctor = await self._doctors.get_by_id(doctor_id)
        if doctor is None or doctor.hospital_id != admin.hospital_id:
            raise DoctorNotFoundError()
        doctor.status = status
        return doctor

    # -- idempotent-completion helpers -------------------------------------------------

    async def _complete_existing_admin(self, user: User) -> HospitalRegistrationOutcome:
        if user.status is not UserStatus.ACTIVE:
            raise AccountSuspendedError()
        if user.role is not Role.HOSPITAL_ADMIN:
            raise OrgRegistrationConflictError(
                "Account is already registered with a different role."
            )
        admin = await self._admins.get_by_user_id(user.id)
        if admin is None:
            raise OrgRegistrationConflictError("Account is in an inconsistent registration state.")
        hospital = await self._hospitals.get_by_id(admin.hospital_id)
        if hospital is None:
            raise OrgRegistrationConflictError("Account is in an inconsistent registration state.")
        await self._accounts.provision_claims(user.firebase_uid, role=user.role, user_id=user.id)
        return HospitalRegistrationOutcome(hospital=hospital, admin=admin, created=False)

    async def _complete_existing_doctor(self, user: User) -> DoctorRegistrationOutcome:
        if user.status is not UserStatus.ACTIVE:
            raise AccountSuspendedError()
        if user.role is not Role.DOCTOR:
            raise OrgRegistrationConflictError(
                "Account is already registered with a different role."
            )
        doctor = await self._doctors.get_by_user_id(user.id)
        if doctor is None:
            raise OrgRegistrationConflictError("Account is in an inconsistent registration state.")
        hospital = await self._hospitals.get_by_id(doctor.hospital_id)
        if hospital is None:
            raise OrgRegistrationConflictError("Account is in an inconsistent registration state.")
        await self._accounts.provision_claims(user.firebase_uid, role=user.role, user_id=user.id)
        return DoctorRegistrationOutcome(doctor=doctor, hospital=hospital, created=False)

    async def _create_hospital_with_hid(self, *, name: str, address: str | None) -> Hospital:
        # Draw-and-insert (ADR-015): the DB unique constraint is the collision check.
        for _ in range(_MAX_HID_ATTEMPTS):
            candidate = Hospital(hid=self._hid_factory(), name=name, address=address)
            try:
                return await self._hospitals.add(candidate)
            except DuplicateHidError:
                continue
        raise HidAllocationError()
