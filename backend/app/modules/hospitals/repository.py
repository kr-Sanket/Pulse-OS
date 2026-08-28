"""Persistence for hospitals-owned tables. Pure persistence — no business rules here.

Flushes run inside savepoints; ``IntegrityError`` becomes a domain error so the service
can handle unique collisions without touching SQLAlchemy session details.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hospitals.errors import DuplicateHospitalIdError
from app.modules.hospitals.models import Hospital


class HospitalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, id: UUID) -> Hospital | None:
        return await self._session.get(Hospital, id)

    async def get_by_hospital_id(self, hospital_id: str) -> Hospital | None:
        result = await self._session.execute(
            select(Hospital).where(Hospital.hospital_id == hospital_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> Sequence[Hospital]:
        result = await self._session.execute(select(Hospital).order_by(Hospital.name))
        return result.scalars().all()

    async def add(self, hospital: Hospital) -> Hospital:
        """Flush a new hospital; the violated unique constraint maps to DuplicateHospitalIdError."""
        try:
            async with self._session.begin_nested():
                self._session.add(hospital)
                await self._session.flush()
        except IntegrityError as exc:
            if "hospital_id" in str(exc.orig):
                raise DuplicateHospitalIdError() from exc
            raise DuplicateHospitalIdError() from exc
        return hospital
