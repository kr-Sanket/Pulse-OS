"""Doctors domain service: doctor registration, affiliation, and profile read.

Framework-free; owns no transaction — the request scope commits (app/core/db.py).
Cross-module dependencies use explicit service interfaces (UserAccountService, HospitalService).
"""

from collections.abc import Sequence
from uuid import UUID

from app.modules.auth.accounts import UserAccountService
from app.modules.auth.domain import Role
from app.modules.doctors.errors import (
    DoctorValidationError,
    DuplicateDoctorError,
    DuplicateRegistrationNumberError,
    InvalidDoctorUserError,
    InvalidHospitalError,
)
from app.modules.doctors.models import Doctor
from app.modules.doctors.repository import DoctorRepository
from app.modules.hospitals.service import HospitalService


class DoctorService:
    def __init__(
        self,
        doctors: DoctorRepository,
        accounts: UserAccountService,
        hospitals: HospitalService,
    ) -> None:
        self._doctors = doctors
        self._accounts = accounts
        self._hospitals = hospitals

    async def create_doctor(
        self,
        *,
        user_id: UUID,
        hospital_id: UUID,
        full_name: str,
        registration_number: str,
        specialty: str,
    ) -> Doctor:
        """Register a clinician profile linked 1:1 with an authenticated DOCTOR user
        and affiliated with a valid Hospital.
        """
        clean_name = full_name.strip()
        clean_reg = registration_number.strip()
        clean_specialty = specialty.strip()

        if not clean_name:
            raise DoctorValidationError("Doctor full name must not be blank.")
        if not clean_reg:
            raise DoctorValidationError("Registration number must not be blank.")
        if not clean_specialty:
            raise DoctorValidationError("Specialty must not be blank.")

        user = await self._accounts.get_by_id(user_id)
        if user is None:
            raise InvalidDoctorUserError("User not found.")
        if user.role is not Role.DOCTOR:
            raise InvalidDoctorUserError("User must have DOCTOR role to be registered as a doctor.")

        hospital = await self._hospitals.get_hospital(hospital_id)
        if hospital is None:
            raise InvalidHospitalError("Hospital not found.")

        existing = await self._doctors.get_by_user_id(user_id)
        if existing is not None:
            raise DuplicateDoctorError("Doctor profile already exists for this user.")

        existing_reg = await self._doctors.get_by_registration_number(clean_reg)
        if existing_reg is not None:
            raise DuplicateRegistrationNumberError("Registration number is already in use.")

        doctor = Doctor(
            user_id=user_id,
            hospital_id=hospital_id,
            full_name=clean_name,
            registration_number=clean_reg,
            specialty=clean_specialty,
        )
        return await self._doctors.add(doctor)

    async def get_by_user_id(self, user_id: UUID) -> Doctor | None:
        return await self._doctors.get_by_user_id(user_id)

    async def get_by_id(self, id: UUID) -> Doctor | None:
        return await self._doctors.get_by_id(id)

    async def get_by_registration_number(self, registration_number: str) -> Doctor | None:
        return await self._doctors.get_by_registration_number(registration_number.strip())

    async def list_by_hospital(self, hospital_id: UUID) -> Sequence[Doctor]:
        return await self._doctors.list_by_hospital_id(hospital_id)
