"""Persistence for records-owned reference tables. Pure persistence — no business rules."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.records.models import Hospital, RecordCategory


class HospitalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_hid(self, hid: str) -> Hospital | None:
        result = await self._session.execute(select(Hospital).where(Hospital.hid == hid))
        return result.scalar_one_or_none()

    async def add(self, hospital: Hospital) -> Hospital:
        self._session.add(hospital)
        await self._session.flush()
        return hospital


class RecordCategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_code(self, code: str) -> RecordCategory | None:
        result = await self._session.execute(
            select(RecordCategory).where(RecordCategory.code == code)
        )
        return result.scalar_one_or_none()

    async def add(self, category: RecordCategory) -> RecordCategory:
        self._session.add(category)
        await self._session.flush()
        return category
