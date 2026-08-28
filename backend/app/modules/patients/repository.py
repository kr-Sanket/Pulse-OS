"""Persistence for patients-owned tables. Pure persistence — no business rules here.

Flushes run inside savepoints; ``IntegrityError`` becomes a domain error so the service
can express draw-and-insert (ADR-012) without touching SQLAlchemy session details.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.patients.errors import DuplicateHealthIdError, DuplicatePatientError
from app.modules.patients.models import Patient


class PatientRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user_id(self, user_id: UUID) -> Patient | None:
        result = await self._session.execute(select(Patient).where(Patient.user_id == user_id))
        return result.scalar_one_or_none()

    async def add(self, patient: Patient) -> Patient:
        """Flush a new patient; the violated unique constraint decides the domain error
        (constraint names/columns are stable across Postgres and SQLite messages)."""
        try:
            async with self._session.begin_nested():
                self._session.add(patient)
                await self._session.flush()
        except IntegrityError as exc:
            if "health_id" in str(exc.orig):
                raise DuplicateHealthIdError() from exc
            raise DuplicatePatientError() from exc
        return patient
