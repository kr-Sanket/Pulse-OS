"""Persistence for doctors-owned tables. Pure persistence — no business rules here.

Flushes run inside savepoints; ``IntegrityError`` is translated into domain errors.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.doctors.errors import (
    DoctorError,
    DuplicateDoctorError,
    DuplicateRegistrationNumberError,
)
from app.modules.doctors.models import Doctor


class DoctorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, id: UUID) -> Doctor | None:
        return await self._session.get(Doctor, id)

    async def get_by_user_id(self, user_id: UUID) -> Doctor | None:
        result = await self._session.execute(select(Doctor).where(Doctor.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_by_registration_number(self, registration_number: str) -> Doctor | None:
        result = await self._session.execute(
            select(Doctor).where(Doctor.registration_number == registration_number)
        )
        return result.scalar_one_or_none()

    async def list_by_hospital_id(self, hospital_id: UUID) -> Sequence[Doctor]:
        result = await self._session.execute(
            select(Doctor).where(Doctor.hospital_id == hospital_id).order_by(Doctor.full_name)
        )
        return result.scalars().all()

    async def add(self, doctor: Doctor) -> Doctor:
        """Flush a new doctor; maps unique constraint collisions to domain errors."""
        try:
            async with self._session.begin_nested():
                self._session.add(doctor)
                await self._session.flush()
        except IntegrityError as exc:
            orig_msg = str(exc.orig)
            if "registration_number" in orig_msg:
                raise DuplicateRegistrationNumberError() from exc
            if "user_id" in orig_msg:
                raise DuplicateDoctorError() from exc
            raise DoctorError("Doctor persistence constraint violation.") from exc
        return doctor
