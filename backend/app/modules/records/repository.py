"""Persistence for records-owned tables. Pure persistence — no business rules here.

Flushes run inside savepoints; ``IntegrityError`` becomes a domain error.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.records.errors import (
    DuplicateCategoryCodeError,
    RecordError,
)
from app.modules.records.models import MedicalRecord, ProcessingStatus, RecordCategory


class RecordCategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, id: UUID) -> RecordCategory | None:
        return await self._session.get(RecordCategory, id)

    async def get_by_code(self, code: str) -> RecordCategory | None:
        result = await self._session.execute(
            select(RecordCategory).where(RecordCategory.code == code)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> Sequence[RecordCategory]:
        result = await self._session.execute(select(RecordCategory).order_by(RecordCategory.code))
        return result.scalars().all()

    async def add(self, category: RecordCategory) -> RecordCategory:
        """Flush a new record category; maps duplicate code collision to
        DuplicateCategoryCodeError.
        """
        try:
            async with self._session.begin_nested():
                self._session.add(category)
                await self._session.flush()
        except IntegrityError as exc:
            raise DuplicateCategoryCodeError() from exc
        return category


class MedicalRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, id: UUID) -> MedicalRecord | None:
        return await self._session.get(MedicalRecord, id)

    async def list_by_patient_id(
        self, patient_id: UUID, *, include_hidden: bool = False
    ) -> Sequence[MedicalRecord]:
        query = select(MedicalRecord).where(MedicalRecord.patient_id == patient_id)
        if not include_hidden:
            query = query.where(MedicalRecord.is_hidden.is_(False))
        query = query.order_by(MedicalRecord.created_at.desc())
        result = await self._session.execute(query)
        return result.scalars().all()

    async def list_by_category_and_patient(
        self, patient_id: UUID, category_id: UUID, *, include_hidden: bool = False
    ) -> Sequence[MedicalRecord]:
        query = select(MedicalRecord).where(
            MedicalRecord.patient_id == patient_id,
            MedicalRecord.category_id == category_id,
        )
        if not include_hidden:
            query = query.where(MedicalRecord.is_hidden.is_(False))
        query = query.order_by(MedicalRecord.created_at.desc())
        result = await self._session.execute(query)
        return result.scalars().all()

    async def list_by_hospital_and_patient(
        self, patient_id: UUID, hospital_id: UUID
    ) -> Sequence[MedicalRecord]:
        query = (
            select(MedicalRecord)
            .where(
                MedicalRecord.patient_id == patient_id,
                MedicalRecord.hospital_id == hospital_id,
            )
            .order_by(MedicalRecord.created_at.desc())
        )
        result = await self._session.execute(query)
        return result.scalars().all()

    async def get_category_existence_counts(
        self, patient_id: UUID
    ) -> Sequence[tuple[UUID, str, str, UUID | None, int]]:
        """Project category-level existence without metadata (DATABASE_DESIGN.md principle).
        Returns tuples of (category_id, category_code, category_display_name, hospital_id, count).
        """
        query = (
            select(
                RecordCategory.id,
                RecordCategory.code,
                RecordCategory.display_name,
                MedicalRecord.hospital_id,
                func.count(MedicalRecord.id).label("record_count"),
            )
            .join(RecordCategory, MedicalRecord.category_id == RecordCategory.id)
            .where(MedicalRecord.patient_id == patient_id, MedicalRecord.is_hidden.is_(False))
            .group_by(
                RecordCategory.id,
                RecordCategory.code,
                RecordCategory.display_name,
                MedicalRecord.hospital_id,
            )
            .order_by(RecordCategory.code)
        )
        result = await self._session.execute(query)
        return result.tuples().all()

    async def add(self, record: MedicalRecord) -> MedicalRecord:
        """Flush a new medical record; maps integrity errors to domain errors."""
        try:
            async with self._session.begin_nested():
                self._session.add(record)
                await self._session.flush()
        except IntegrityError as exc:
            raise RecordError("Medical record persistence constraint violation.") from exc
        return record

    async def update_status(
        self, id: UUID, status: ProcessingStatus, failure_reason: str | None = None
    ) -> MedicalRecord | None:
        record = await self.get_by_id(id)
        if record is None:
            return None
        record.processing_status = status
        record.failure_reason = failure_reason
        await self._session.flush()
        return record

    async def set_hidden(self, id: UUID, is_hidden: bool) -> MedicalRecord | None:
        record = await self.get_by_id(id)
        if record is None:
            return None
        record.is_hidden = is_hidden
        await self._session.flush()
        return record
