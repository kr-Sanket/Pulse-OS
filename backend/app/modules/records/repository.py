"""Persistence for records-owned tables. Pure persistence — no business rules.

Flushes run inside savepoints where a unique constraint doubles as a domain check
(draw-and-insert HIDs, 1:1 profile rows); ``IntegrityError`` becomes a domain error so
services never touch SQLAlchemy session details. Paginated listings use keyset cursors
over ``(created_at DESC, id DESC)`` (app/shared/pagination.py) — never OFFSET.
"""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, Select, and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.records.errors import DuplicateHidError, DuplicateProfileError
from app.modules.records.models import (
    Doctor,
    Hospital,
    HospitalAdmin,
    MedicalRecord,
    RecordCategory,
)
from app.shared.pagination import CursorKey

#: A record with its display context: category always, uploading hospital when present.
RecordRow = tuple[MedicalRecord, RecordCategory, Hospital | None]

#: A member of hospital staff with the hospital they belong to — the row the display
#: projection is built from (app/modules/records/directory.py). Joined rather than fetched
#: per person: these listings resolve a whole page of identities at once.
ClinicianRow = tuple[Doctor, Hospital]
AdminRow = tuple[HospitalAdmin, Hospital]


def _keyset_filter(
    created_col: InstrumentedAttribute[datetime],
    id_col: InstrumentedAttribute[UUID],
    after: CursorKey,
) -> ColumnElement[bool]:
    """WHERE clause for "strictly after ``after`` in (created_at DESC, id DESC) order".

    Spelled as an OR (not a row-value comparison) because SQLite lacks tuple comparison.
    """
    return or_(
        created_col < after.created_at,
        and_(created_col == after.created_at, id_col < after.item_id),
    )


class HospitalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, hospital_id: UUID) -> Hospital | None:
        return await self._session.get(Hospital, hospital_id)

    async def get_by_hid(self, hid: str) -> Hospital | None:
        result = await self._session.execute(select(Hospital).where(Hospital.hid == hid))
        return result.scalar_one_or_none()

    async def list_by_ids(self, hospital_ids: Collection[UUID]) -> list[Hospital]:
        """Batch read for the display projection: one statement per page of results.

        The empty case short-circuits rather than emitting ``IN ()`` — a page that refers
        to no hospital should cost no round trip.
        """
        if not hospital_ids:
            return []
        result = await self._session.execute(select(Hospital).where(Hospital.id.in_(hospital_ids)))
        return list(result.scalars())

    async def add(self, hospital: Hospital) -> Hospital:
        """Flush a new hospital; an ``hid`` collision becomes ``DuplicateHidError`` so the
        service can express draw-and-insert (ADR-015)."""
        try:
            async with self._session.begin_nested():
                self._session.add(hospital)
                await self._session.flush()
        except IntegrityError as exc:
            raise DuplicateHidError() from exc
        return hospital


class RecordCategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_code(self, code: str) -> RecordCategory | None:
        result = await self._session.execute(
            select(RecordCategory).where(RecordCategory.code == code)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[RecordCategory]:
        result = await self._session.execute(select(RecordCategory).order_by(RecordCategory.code))
        return list(result.scalars())

    async def add(self, category: RecordCategory) -> RecordCategory:
        self._session.add(category)
        await self._session.flush()
        return category


class DoctorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, doctor_id: UUID) -> Doctor | None:
        return await self._session.get(Doctor, doctor_id)

    async def get_by_user_id(self, user_id: UUID) -> Doctor | None:
        result = await self._session.execute(select(Doctor).where(Doctor.user_id == user_id))
        return result.scalar_one_or_none()

    async def list_with_hospital_by_ids(self, doctor_ids: Collection[UUID]) -> list[ClinicianRow]:
        """Practitioners by their own id, each with the hospital they practise at."""
        return await self._joined(Doctor.id, doctor_ids)

    async def list_with_hospital_by_user_ids(
        self, user_ids: Collection[UUID]
    ) -> list[ClinicianRow]:
        """The same rows addressed by account id — what an audit entry records its actor as."""
        return await self._joined(Doctor.user_id, user_ids)

    async def _joined(
        self, column: InstrumentedAttribute[UUID], values: Collection[UUID]
    ) -> list[ClinicianRow]:
        if not values:
            return []
        result = await self._session.execute(
            select(Doctor, Hospital)
            .join(Hospital, Doctor.hospital_id == Hospital.id)
            .where(column.in_(values))
        )
        return [(doctor, hospital) for doctor, hospital in result.all()]

    async def add(self, doctor: Doctor) -> Doctor:
        """Flush a new doctor; the unique ``user_id`` makes the 1:1 profile rule a
        constraint, not a hope (concurrent-registration races surface as a domain error).
        """
        try:
            async with self._session.begin_nested():
                self._session.add(doctor)
                await self._session.flush()
        except IntegrityError as exc:
            raise DuplicateProfileError() from exc
        return doctor

    async def list_page_by_hospital(
        self, hospital_id: UUID, *, after: CursorKey | None, limit: int
    ) -> list[Doctor]:
        """One page of a hospital's doctors, newest first. Fetches ``limit`` rows; the
        service asks for one extra to detect whether a next page exists."""
        query: Select[tuple[Doctor]] = (
            select(Doctor)
            .where(Doctor.hospital_id == hospital_id)
            .order_by(Doctor.created_at.desc(), Doctor.id.desc())
            .limit(limit)
        )
        if after is not None:
            query = query.where(_keyset_filter(Doctor.created_at, Doctor.id, after))
        result = await self._session.execute(query)
        return list(result.scalars())


class HospitalAdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user_id(self, user_id: UUID) -> HospitalAdmin | None:
        result = await self._session.execute(
            select(HospitalAdmin).where(HospitalAdmin.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_with_hospital_by_user_ids(self, user_ids: Collection[UUID]) -> list[AdminRow]:
        """Administrators by account id, each with their hospital — the other kind of actor
        an audit entry can name (a hospital upload is theirs, not a clinician's)."""
        if not user_ids:
            return []
        result = await self._session.execute(
            select(HospitalAdmin, Hospital)
            .join(Hospital, HospitalAdmin.hospital_id == Hospital.id)
            .where(HospitalAdmin.user_id.in_(user_ids))
        )
        return [(admin, hospital) for admin, hospital in result.all()]

    async def add(self, admin: HospitalAdmin) -> HospitalAdmin:
        try:
            async with self._session.begin_nested():
                self._session.add(admin)
                await self._session.flush()
        except IntegrityError as exc:
            raise DuplicateProfileError() from exc
        return admin


class MedicalRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, record: MedicalRecord) -> MedicalRecord:
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_with_context(self, record_id: UUID) -> RecordRow | None:
        result = await self._session.execute(
            self._context_query().where(MedicalRecord.id == record_id)
        )
        row = result.first()
        return (row[0], row[1], row[2]) if row is not None else None

    async def list_page(
        self,
        *,
        patient_id: UUID | None = None,
        uploaded_by_hospital_id: UUID | None = None,
        category_id: UUID | None = None,
        after: CursorKey | None = None,
        limit: int,
    ) -> list[RecordRow]:
        """One page of record metadata with display context, newest first.

        Exactly one of ``patient_id`` / ``uploaded_by_hospital_id`` must be set — every
        listing is scoped to a relationship (ADR-013 layer 2); an unscoped listing of
        medical records must not even be expressible.
        """
        if (patient_id is None) == (uploaded_by_hospital_id is None):
            raise ValueError("exactly one of patient_id/uploaded_by_hospital_id is required")
        query = self._context_query().limit(limit)
        if patient_id is not None:
            query = query.where(MedicalRecord.patient_id == patient_id)
        if uploaded_by_hospital_id is not None:
            query = query.where(MedicalRecord.uploaded_by_hospital_id == uploaded_by_hospital_id)
        if category_id is not None:
            query = query.where(MedicalRecord.category_id == category_id)
        if after is not None:
            query = query.where(_keyset_filter(MedicalRecord.created_at, MedicalRecord.id, after))
        result = await self._session.execute(query)
        return [(row[0], row[1], row[2]) for row in result.all()]

    def _context_query(self) -> Select[tuple[MedicalRecord, RecordCategory, Hospital]]:
        # The Hospital column is NULL for locker uploads (outer join) — SQLAlchemy's
        # Select typing cannot express that, so RecordRow carries the honest type.
        return (
            select(MedicalRecord, RecordCategory, Hospital)
            .join(RecordCategory, MedicalRecord.category_id == RecordCategory.id)
            .outerjoin(Hospital, MedicalRecord.uploaded_by_hospital_id == Hospital.id)
            .order_by(MedicalRecord.created_at.desc(), MedicalRecord.id.desc())
        )
