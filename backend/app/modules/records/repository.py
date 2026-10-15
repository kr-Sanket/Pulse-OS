"""Persistence for records-owned tables. Pure persistence — no business rules.

Flushes run inside savepoints where a unique constraint doubles as a domain check
(draw-and-insert HIDs, 1:1 profile rows); ``IntegrityError`` becomes a domain error so
services never touch SQLAlchemy session details. Paginated listings use keyset cursors
(app/shared/pagination.py) — never OFFSET: ``(created_at DESC, id DESC)`` for listings
ordered by when a row appeared, and ``(date_of_service, id)`` in either direction for the
record listings, which a patient reads as a clinical history rather than an inbox.
"""

from collections.abc import Collection
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.records.errors import DuplicateHidError, DuplicateProfileError
from app.modules.records.models import (
    Doctor,
    Hospital,
    HospitalAdmin,
    HospitalVerificationStatus,
    MedicalRecord,
    RecordCategory,
)
from app.shared.pagination import CursorKey, DateCursor, SortDirection

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


def _date_keyset_filter(after: DateCursor) -> ColumnElement[bool]:
    """WHERE clause for "strictly after ``after``" in the direction the cursor was issued for.

    The comparison flips with the direction, and both halves must flip together: under
    ``oldest`` the next page is dates *greater* than the cursor's, and within the cursor's
    own date it is the ids *greater* than it. Getting one half right and the other wrong
    is invisible until a page boundary lands inside a run of same-date records — which,
    with a handful of records per clinical day, is most boundaries.

    Spelled as an OR rather than a row-value comparison because SQLite lacks tuple
    comparison, matching ``_keyset_filter`` above.
    """
    date_col = MedicalRecord.date_of_service
    id_col = MedicalRecord.id
    if after.sort is SortDirection.OLDEST_FIRST:
        return or_(
            date_col > after.sort_date,
            and_(date_col == after.sort_date, id_col > after.item_id),
        )
    return or_(
        date_col < after.sort_date,
        and_(date_col == after.sort_date, id_col < after.item_id),
    )


#: ``\`` escapes the LIKE metacharacters below. Chosen over the default (no escape clause)
#: because a patient searching for "100_mg" or "50%" must match those literally rather than
#: having them read as wildcards.
_LIKE_ESCAPE: Final = "\\"


def escape_like(term: str) -> str:
    """Make ``term`` a literal substring pattern for ILIKE.

    The backslash goes first: escaping it after ``%`` and ``_`` would double the escapes
    this function had just introduced.
    """
    escaped = term.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
    for metacharacter in ("%", "_"):
        escaped = escaped.replace(metacharacter, f"{_LIKE_ESCAPE}{metacharacter}")
    return f"%{escaped}%"


def _search_filter(term: str) -> ColumnElement[bool]:
    """Case-insensitive substring match over the two text columns the record itself owns.

    Deliberately not the joined category or hospital name: the category is already a
    first-class filter, and widening the predicate across a join buys nothing the chips do
    not already do. ``description`` is nullable, and ``ILIKE`` on NULL is NULL — falsy in a
    WHERE, which is the behaviour we want, so no COALESCE is needed.
    """
    pattern = escape_like(term)
    return or_(
        MedicalRecord.original_filename.ilike(pattern, escape=_LIKE_ESCAPE),
        MedicalRecord.description.ilike(pattern, escape=_LIKE_ESCAPE),
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

    async def list_all(
        self,
        *,
        verification_status: HospitalVerificationStatus | None = None,
    ) -> list[Hospital]:
        """List all hospitals, newest first, with optional verification status filter."""
        stmt = select(Hospital).order_by(Hospital.created_at.desc(), Hospital.hid.asc())
        if verification_status is not None:
            stmt = stmt.where(Hospital.verification_status == verification_status)
        result = await self._session.execute(stmt)
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
        query = (
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

    async def update(self, record: MedicalRecord) -> MedicalRecord:
        """Persist changes already applied to a loaded row.

        No column list and no keyword arguments, for the reason ``PatientRepository.update``
        gives: which fields may change is a domain rule, and restating it here would give
        the schema a second opinion about it. Today the service assigns exactly one
        attribute — ``is_hidden`` — and ``updated_at`` is stamped by TimestampMixin's
        ``onupdate`` rather than by hand.

        No savepoint, unlike ``add``: this touches no unique column, so the only failures
        available to it are ones no domain error could usefully translate.
        """
        self._session.add(record)
        await self._session.flush()
        return record

    async def list_category_ids_with_records(self, patient_id: UUID) -> list[UUID]:
        """The categories this patient actually holds records in — ids only.

        The existence projection's whole query (docs/SYSTEM_ARCHITECTURE.md §Consent Flow
        step 1): one grouped scan of ``ix`` on ``patient_id``, returning nothing but the
        category. No row, no filename, no hospital, no date ever leaves this method, so a
        caller that may only learn *whether* records exist cannot accidentally be handed
        more. Hidden records are excluded — a record the patient has hidden must not exist
        as far as anyone but the patient is concerned (the same rule service.py applies to
        content reads).
        """
        result = await self._session.execute(
            select(MedicalRecord.category_id)
            .where(MedicalRecord.patient_id == patient_id, MedicalRecord.is_hidden.is_(False))
            .group_by(MedicalRecord.category_id)
        )
        return list(result.scalars())

    async def get_with_context(self, record_id: UUID) -> RecordRow | None:
        rows = await self._context_rows(MedicalRecord.id == record_id)
        return rows[0] if rows else None

    async def list_page(
        self,
        *,
        patient_id: UUID | None = None,
        uploaded_by_hospital_id: UUID | None = None,
        category_id: UUID | None = None,
        search: str | None = None,
        sort: SortDirection = SortDirection.NEWEST_FIRST,
        after: DateCursor | None = None,
        limit: int,
    ) -> list[RecordRow]:
        """One page of record metadata with display context, in clinical-date order.

        Exactly one of ``patient_id`` / ``uploaded_by_hospital_id`` must be set — every
        listing is scoped to a relationship (ADR-013 layer 2); an unscoped listing of
        medical records must not even be expressible.

        ``search`` matches the record's own filename and description. It is offered here and
        **not** on ``list_page_for_grantee`` on purpose: see that method.
        """
        if (patient_id is None) == (uploaded_by_hospital_id is None):
            raise ValueError("exactly one of patient_id/uploaded_by_hospital_id is required")
        criteria: list[ColumnElement[bool]] = []
        if patient_id is not None:
            criteria.append(MedicalRecord.patient_id == patient_id)
        if uploaded_by_hospital_id is not None:
            criteria.append(MedicalRecord.uploaded_by_hospital_id == uploaded_by_hospital_id)
        if category_id is not None:
            criteria.append(MedicalRecord.category_id == category_id)
        if search:
            criteria.append(_search_filter(search))
        if after is not None:
            criteria.append(_date_keyset_filter(after))
        return await self._context_rows(*criteria, sort=sort, limit=limit)

    async def list_page_for_grantee(
        self,
        *,
        patient_id: UUID,
        category_ids: Collection[UUID],
        after: DateCursor | None = None,
        limit: int,
    ) -> list[RecordRow]:
        """One page of the records a consented clinician may read, newest first (ADR-020).

        Ordering moved to ``date_of_service`` with the patient listing, for the same reason
        (see ``_context_rows``) — the clinician's page had the identical collapse. It takes
        **no** ``search``, and that omission is a security property rather than an
        oversight: ``GrantedRecordResponse`` deliberately withholds ``original_filename`` and
        ``description``, and a search over exactly those two withheld columns would turn this
        listing into an oracle for them — result counts would let a clinician recover a
        diagnosis-bearing description one substring at a time. Sorting reveals nothing the
        page does not already show; searching would.

        Separate from ``list_page`` rather than a pair of extra arguments on it, for the
        reason ``list_category_ids_with_records`` is separate: the safety of this listing
        is in what its signature cannot express. ``category_ids`` is required and must be
        non-empty, so a scope-free clinician listing is not constructible; hidden records
        are filtered unconditionally, with no flag to turn it off. ``list_page`` needs the
        opposite defaults — its owner and its uploading hospital are entitled to see a
        hidden record (app/modules/records/service.py) — and any argument that reconciled
        both would have to default to one of them, which is how the unsafe default gets
        chosen by accident.

        The caller supplies the granted set; deciding what is in it belongs to ``consent``,
        never here. Category and uploading hospital arrive on the joined row, so a page
        costs one statement no matter how many records it holds.
        """
        if not category_ids:
            raise ValueError("category_ids must be non-empty: a listing is always grant-scoped")
        criteria: list[ColumnElement[bool]] = [
            MedicalRecord.patient_id == patient_id,
            MedicalRecord.category_id.in_(category_ids),
            MedicalRecord.is_hidden.is_(False),
        ]
        if after is not None:
            criteria.append(_date_keyset_filter(after))
        return await self._context_rows(*criteria, limit=limit)

    async def _context_rows(
        self,
        *criteria: ColumnElement[bool],
        sort: SortDirection = SortDirection.NEWEST_FIRST,
        limit: int | None = None,
    ) -> list[RecordRow]:
        """Run the joined listing query, ordered by *clinical* date, and return its rows.

        Ordering by ``date_of_service`` rather than ``created_at`` is a correctness fix, not
        a preference. ``created_at`` defaults to the transaction clock, so every record
        written in one transaction shares an instant and the sort collapses onto the UUID
        tie-breaker — i.e. onto nothing. A bulk import made that visible (103 records, one
        ``created_at``, dates spanning 1963 to 2018), but any multi-record write has it, and a
        patient reads this list as a history rather than an inbox either way.

        ``id`` remains the tie-breaker, in the same direction as the date, so the order is
        total and a keyset can address every row unambiguously.

        Built, executed and unpacked in one place so the statement's type is only ever
        inferred: SQLAlchemy 2.0 spells it ``Select[tuple[...]]`` and 2.1 ``Select[...]``, and
        no single annotation is valid under both.
        """
        # The Hospital column is NULL for locker uploads (outer join) — SQLAlchemy's
        # Select typing cannot express that, so RecordRow carries the honest type.
        date_col = MedicalRecord.date_of_service
        id_col = MedicalRecord.id
        ordering = (
            (date_col.asc(), id_col.asc())
            if sort is SortDirection.OLDEST_FIRST
            else (date_col.desc(), id_col.desc())
        )
        query = (
            select(MedicalRecord, RecordCategory, Hospital)
            .join(RecordCategory, MedicalRecord.category_id == RecordCategory.id)
            .outerjoin(Hospital, MedicalRecord.uploaded_by_hospital_id == Hospital.id)
            .where(*criteria)
            .order_by(*ordering)
        )
        if limit is not None:
            query = query.limit(limit)
        result = await self._session.execute(query)
        return [(row[0], row[1], row[2]) for row in result.all()]
