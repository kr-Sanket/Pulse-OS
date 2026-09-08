"""records repository tests: CRUD, duplicate translation, and keyset pagination."""

import asyncio
from datetime import date, datetime
from uuid import UUID, uuid4

import pytest
from app.modules.auth.domain import Role
from app.modules.auth.models import User
from app.modules.patients.models import Patient
from app.modules.records.errors import DuplicateHidError, DuplicateProfileError
from app.modules.records.models import (
    Doctor,
    Hospital,
    HospitalAdmin,
    MedicalRecord,
    RecordCategory,
    RecordOrigin,
)
from app.modules.records.repository import (
    DoctorRepository,
    HospitalAdminRepository,
    HospitalRepository,
    MedicalRecordRepository,
    RecordCategoryRepository,
    escape_like,
)
from app.shared.pagination import CursorKey, DateCursor, SortDirection
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import sqlite_session


async def _user(session: AsyncSession, role: Role = Role.DOCTOR) -> User:
    user = User(firebase_uid=f"fb-{uuid4()}", role=role)
    session.add(user)
    await session.flush()
    return user


async def _hospital(session: AsyncSession, hid: str = "HID-9001") -> Hospital:
    hospital = Hospital(hid=hid, name=f"Hospital {hid}")
    session.add(hospital)
    await session.flush()
    return hospital


async def _patient(session: AsyncSession) -> Patient:
    user = await _user(session, role=Role.PATIENT)
    patient = Patient(
        user_id=user.id,
        health_id=f"PHI-IND-2026-{str(uuid4())[:7].upper()}"[:20],
        full_name="Test Patient",
    )
    session.add(patient)
    await session.flush()
    return patient


async def _record(
    session: AsyncSession,
    *,
    patient_id: UUID,
    category: RecordCategory,
    hospital_id: UUID | None,
    created_at: datetime,
    date_of_service: date = date(2026, 1, 1),
    original_filename: str = "r.pdf",
    description: str | None = None,
) -> MedicalRecord:
    record = MedicalRecord(
        patient_id=patient_id,
        category_id=category.id,
        origin=RecordOrigin.HOSPITAL_UPLOAD if hospital_id else RecordOrigin.PATIENT_LOCKER,
        uploaded_by_hospital_id=hospital_id,
        date_of_service=date_of_service,
        description=description,
        original_filename=original_filename,
        content_type="application/pdf",
        size_bytes=5,
        s3_key=f"records/{patient_id}/{uuid4()}",
        created_at=created_at,
    )
    session.add(record)
    await session.flush()
    return record


def test_hospital_add_translates_hid_collision() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            repo = HospitalRepository(session)
            await repo.add(Hospital(hid="HID-1111", name="A"))
            with pytest.raises(DuplicateHidError):
                await repo.add(Hospital(hid="HID-1111", name="B"))
            # The savepoint contained the failure: the session stays usable.
            assert (await repo.get_by_hid("HID-1111")) is not None

    asyncio.run(scenario())


def test_doctor_and_admin_duplicate_user_translation() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            hospital = await _hospital(session)
            doctor_user = await _user(session)
            doctors = DoctorRepository(session)
            await doctors.add(
                Doctor(
                    user_id=doctor_user.id,
                    hospital_id=hospital.id,
                    full_name="Dr. A",
                    registration_number="R-1",
                )
            )
            with pytest.raises(DuplicateProfileError):
                await doctors.add(
                    Doctor(
                        user_id=doctor_user.id,
                        hospital_id=hospital.id,
                        full_name="Dr. A again",
                        registration_number="R-2",
                    )
                )

            admin_user = await _user(session, role=Role.HOSPITAL_ADMIN)
            admins = HospitalAdminRepository(session)
            await admins.add(
                HospitalAdmin(user_id=admin_user.id, hospital_id=hospital.id, full_name="Admin")
            )
            with pytest.raises(DuplicateProfileError):
                await admins.add(
                    HospitalAdmin(
                        user_id=admin_user.id, hospital_id=hospital.id, full_name="Admin again"
                    )
                )

    asyncio.run(scenario())


def test_doctor_pagination_pages_through_a_hospital_only() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            mine = await _hospital(session, "HID-1001")
            other = await _hospital(session, "HID-1002")
            doctors = DoctorRepository(session)
            for index in range(5):
                user = await _user(session)
                await doctors.add(
                    Doctor(
                        user_id=user.id,
                        hospital_id=mine.id,
                        full_name=f"Dr. {index}",
                        registration_number=f"R-{index}",
                        created_at=datetime(2026, 1, 1, 12, 0, index),
                    )
                )
            outsider = await _user(session)
            await doctors.add(
                Doctor(
                    user_id=outsider.id,
                    hospital_id=other.id,
                    full_name="Dr. Elsewhere",
                    registration_number="R-X",
                    created_at=datetime(2026, 1, 1, 12, 0, 30),
                )
            )

            first = await doctors.list_page_by_hospital(mine.id, after=None, limit=3)
            assert [d.full_name for d in first] == ["Dr. 4", "Dr. 3", "Dr. 2"]

            after = CursorKey(created_at=first[-1].created_at, item_id=first[-1].id)
            second = await doctors.list_page_by_hospital(mine.id, after=after, limit=3)
            assert [d.full_name for d in second] == ["Dr. 1", "Dr. 0"]
            # The other hospital's doctor never appears in any page.

    asyncio.run(scenario())


def test_record_listing_is_scoped_filtered_and_keyset_paginated() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            hospital = await _hospital(session)
            patient = await _patient(session)
            other_patient = await _patient(session)
            categories = RecordCategoryRepository(session)
            cbc = await categories.add(RecordCategory(code="CBC", display_name="CBC"))
            mri = await categories.add(RecordCategory(code="MRI", display_name="MRI"))

            records = MedicalRecordRepository(session)
            # Distinct clinical dates, ascending with the loop, so "newest first" has one
            # correct answer. created_at deliberately moves the *other* way: the listing
            # must order by care date, not by the row's insertion time.
            for offset, category in enumerate([cbc, cbc, mri]):
                await _record(
                    session,
                    patient_id=patient.id,
                    category=category,
                    hospital_id=hospital.id,
                    created_at=datetime(2026, 2, 1, 10, 0, 10 - offset),
                    date_of_service=date(2026, 1, 1 + offset),
                )
            await _record(
                session,
                patient_id=other_patient.id,
                category=cbc,
                hospital_id=None,
                created_at=datetime(2026, 2, 1, 11, 0, 0),
                date_of_service=date(2026, 6, 1),
            )

            mine = await records.list_page(patient_id=patient.id, limit=10)
            assert len(mine) == 3
            assert all(row[0].patient_id == patient.id for row in mine)
            # Newest first, with joined context.
            assert [row[1].code for row in mine] == ["MRI", "CBC", "CBC"]
            assert all(row[2] is not None and row[2].hid == hospital.hid for row in mine)

            only_cbc = await records.list_page(patient_id=patient.id, category_id=cbc.id, limit=10)
            assert [row[1].code for row in only_cbc] == ["CBC", "CBC"]

            by_hospital = await records.list_page(uploaded_by_hospital_id=hospital.id, limit=10)
            assert len(by_hospital) == 3  # the locker record of other_patient is absent

            first_page = await records.list_page(patient_id=patient.id, limit=2)
            last = first_page[-1][0]
            second_page = await records.list_page(
                patient_id=patient.id,
                after=DateCursor(
                    sort=SortDirection.NEWEST_FIRST,
                    sort_date=last.date_of_service,
                    item_id=last.id,
                ),
                limit=2,
            )
            assert len(second_page) == 1
            ids = {row[0].id for row in first_page} | {row[0].id for row in second_page}
            assert len(ids) == 3  # no overlap, no loss

    asyncio.run(scenario())


def test_record_listing_requires_exactly_one_scope() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            records = MedicalRecordRepository(session)
            with pytest.raises(ValueError, match="exactly one"):
                await records.list_page(limit=10)
            with pytest.raises(ValueError, match="exactly one"):
                await records.list_page(
                    patient_id=uuid4(), uploaded_by_hospital_id=uuid4(), limit=10
                )

    asyncio.run(scenario())


def test_get_with_context_returns_none_for_unknown_id() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            records = MedicalRecordRepository(session)
            assert await records.get_with_context(uuid4()) is None

    asyncio.run(scenario())


def test_category_existence_is_grouped_scoped_and_hides_hidden_records() -> None:
    """The existence projection's query: one row per category the patient actually holds,
    nothing from anyone else, and nothing the patient has hidden."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            hospital = await _hospital(session)
            patient = await _patient(session)
            other_patient = await _patient(session)
            categories = RecordCategoryRepository(session)
            cbc = await categories.add(RecordCategory(code="CBC", display_name="CBC"))
            mri = await categories.add(RecordCategory(code="MRI", display_name="MRI"))
            xray = await categories.add(RecordCategory(code="XRAY", display_name="X-Ray"))

            records = MedicalRecordRepository(session)
            # Two CBCs collapse to one row; MRI adds a second.
            for second, category in enumerate([cbc, cbc, mri]):
                await _record(
                    session,
                    patient_id=patient.id,
                    category=category,
                    hospital_id=hospital.id,
                    created_at=datetime(2026, 2, 1, 10, 0, second),
                )
            hidden = await _record(
                session,
                patient_id=patient.id,
                category=xray,
                hospital_id=None,
                created_at=datetime(2026, 2, 1, 11, 0, 0),
            )
            hidden.is_hidden = True
            # Another patient's record must not appear in this patient's projection.
            await _record(
                session,
                patient_id=other_patient.id,
                category=xray,
                hospital_id=hospital.id,
                created_at=datetime(2026, 2, 1, 12, 0, 0),
            )
            await session.flush()

            held = await records.list_category_ids_with_records(patient.id)

            assert set(held) == {cbc.id, mri.id}
            assert len(held) == 2  # grouped: the second CBC does not produce a second row
            assert xray.id not in held  # hidden from everyone but the patient

    asyncio.run(scenario())


def test_category_existence_is_empty_for_a_patient_with_no_records() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            patient = await _patient(session)

            assert (
                await MedicalRecordRepository(session).list_category_ids_with_records(patient.id)
                == []
            )

    asyncio.run(scenario())


def test_grantee_listing_is_scoped_to_patient_categories_and_visible_records() -> None:
    """``list_page_for_grantee``: the three filters that make a clinician listing safe, and
    the keyset pagination it shares with every other listing (ADR-020)."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            hospital = await _hospital(session)
            patient = await _patient(session)
            other_patient = await _patient(session)
            categories = RecordCategoryRepository(session)
            cbc = await categories.add(RecordCategory(code="CBC", display_name="CBC"))
            mri = await categories.add(RecordCategory(code="MRI", display_name="MRI"))
            records = MedicalRecordRepository(session)

            # Distinct clinical dates ascending; created_at descending, so this also pins
            # that the grantee listing orders by care date rather than insertion time.
            for offset, category in enumerate([cbc, cbc, cbc, mri]):
                await _record(
                    session,
                    patient_id=patient.id,
                    category=category,
                    hospital_id=hospital.id,
                    created_at=datetime(2026, 2, 1, 10, 0, 20 - offset),
                    date_of_service=date(2026, 1, 1 + offset),
                )
            hidden = await _record(
                session,
                patient_id=patient.id,
                category=cbc,
                hospital_id=hospital.id,
                created_at=datetime(2026, 2, 1, 10, 0, 9),
                date_of_service=date(2026, 5, 1),
            )
            hidden.is_hidden = True
            await _record(
                session,
                patient_id=other_patient.id,
                category=cbc,
                hospital_id=hospital.id,
                created_at=datetime(2026, 2, 1, 11, 0, 0),
            )
            await session.flush()

            granted = await records.list_page_for_grantee(
                patient_id=patient.id, category_ids=[cbc.id], limit=10
            )
            assert [row[1].code for row in granted] == ["CBC", "CBC", "CBC"]
            assert all(row[0].patient_id == patient.id for row in granted)
            assert hidden.id not in {row[0].id for row in granted}
            # Joined context arrives on the same row — no per-record lookup.
            assert all(row[2] is not None and row[2].hid == hospital.hid for row in granted)

            both = await records.list_page_for_grantee(
                patient_id=patient.id, category_ids=[cbc.id, mri.id], limit=10
            )
            assert [row[1].code for row in both] == ["MRI", "CBC", "CBC", "CBC"]

            first_page = await records.list_page_for_grantee(
                patient_id=patient.id, category_ids=[cbc.id], limit=2
            )
            last = first_page[-1][0]
            second_page = await records.list_page_for_grantee(
                patient_id=patient.id,
                category_ids=[cbc.id],
                after=DateCursor(
                    sort=SortDirection.NEWEST_FIRST,
                    sort_date=last.date_of_service,
                    item_id=last.id,
                ),
                limit=2,
            )
            assert len(second_page) == 1
            ids = {row[0].id for row in first_page} | {row[0].id for row in second_page}
            assert len(ids) == 3  # no overlap, no loss

    asyncio.run(scenario())


def test_a_grantee_listing_without_a_granted_category_is_not_expressible() -> None:
    """The empty set is refused rather than silently matching nothing: a listing with no
    scope is a bug in the caller, and the service short-circuits before it can happen."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            records = MedicalRecordRepository(session)
            with pytest.raises(ValueError, match="non-empty"):
                await records.list_page_for_grantee(patient_id=uuid4(), category_ids=[], limit=10)

    asyncio.run(scenario())


# -- listing controls: clinical-date ordering, bidirectional keyset, search --------------


async def _dated(
    session: AsyncSession,
    patient_id: UUID,
    category: RecordCategory,
    days: list[int],
    **kwargs: object,
) -> list[MedicalRecord]:
    """Records on the given days of 2026-01, all written at one instant.

    The shared ``created_at`` is the point: it is what a bulk import produces, and it makes
    every assertion below fail if the listing ever reverts to ordering by insertion time.
    """
    out = []
    for day in days:
        out.append(
            await _record(
                session,
                patient_id=patient_id,
                category=category,
                hospital_id=None,
                created_at=datetime(2026, 2, 1, 12, 0, 0),
                date_of_service=date(2026, 1, day),
                **kwargs,  # type: ignore[arg-type]
            )
        )
    return out


async def _walk(
    records: MedicalRecordRepository, patient_id: UUID, sort: SortDirection, page_size: int
) -> list[MedicalRecord]:
    """Page through the whole listing, following cursors exactly as a client would."""
    seen: list[MedicalRecord] = []
    after: DateCursor | None = None
    while True:
        rows = await records.list_page(
            patient_id=patient_id, sort=sort, after=after, limit=page_size + 1
        )
        page = [row[0] for row in rows[:page_size]]
        seen.extend(page)
        if len(rows) <= page_size:
            return seen
        last = page[-1]
        after = DateCursor(sort=sort, sort_date=last.date_of_service, item_id=last.id)


def test_the_listing_orders_by_clinical_date_not_insertion_time() -> None:
    """The defect this slice fixes. ``created_at`` defaults to the transaction clock, so a
    bulk import gives every record one instant and the old sort collapsed onto the random
    UUID tie-breaker."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            patient = await _patient(session)
            cbc = await RecordCategoryRepository(session).add(
                RecordCategory(code="CBC", display_name="CBC")
            )
            records = MedicalRecordRepository(session)
            written = await _dated(session, patient.id, cbc, [3, 1, 2])
            # Precondition: one insertion instant for all three, so created_at carries no
            # ordering information at all and only date_of_service can produce the answer.
            assert len({record.created_at for record in written}) == 1

            newest = await records.list_page(patient_id=patient.id, limit=10)
            assert [row[0].date_of_service.day for row in newest] == [3, 2, 1]

            oldest = await records.list_page(
                patient_id=patient.id, sort=SortDirection.OLDEST_FIRST, limit=10
            )
            assert [row[0].date_of_service.day for row in oldest] == [1, 2, 3]

    asyncio.run(scenario())


def test_keyset_pagination_is_total_in_both_directions_across_ties() -> None:
    """Nine records over three dates, so every page boundary lands inside a tie.

    A keyset that compares only the date loses the rest of a tied run or serves it twice;
    one that flips the date comparison but not the id comparison breaks in exactly one
    direction. Walking both, at three page sizes, catches all three mistakes.
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            patient = await _patient(session)
            cbc = await RecordCategoryRepository(session).add(
                RecordCategory(code="CBC", display_name="CBC")
            )
            records = MedicalRecordRepository(session)
            await _dated(session, patient.id, cbc, [1, 1, 1, 2, 2, 2, 3, 3, 3])

            for page_size in (1, 2, 4):
                for sort in (SortDirection.NEWEST_FIRST, SortDirection.OLDEST_FIRST):
                    walked = await _walk(records, patient.id, sort, page_size)
                    ids = [r.id for r in walked]
                    assert len(ids) == 9, f"{sort}/{page_size}: served {len(ids)}"
                    assert len(set(ids)) == 9, f"{sort}/{page_size}: duplicates"
                    days = [r.date_of_service.day for r in walked]
                    expected = [3, 3, 3, 2, 2, 2, 1, 1, 1]
                    if sort is SortDirection.OLDEST_FIRST:
                        expected = list(reversed(expected))
                    assert days == expected, f"{sort}/{page_size}: {days}"

            # The two directions must be exact mirrors, ties included.
            forward = [
                r.id for r in await _walk(records, patient.id, SortDirection.NEWEST_FIRST, 2)
            ]
            backward = [
                r.id for r in await _walk(records, patient.id, SortDirection.OLDEST_FIRST, 2)
            ]
            assert forward == list(reversed(backward))

    asyncio.run(scenario())


def test_search_matches_the_records_own_text_columns() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            patient = await _patient(session)
            cbc = await RecordCategoryRepository(session).add(
                RecordCategory(code="CBC", display_name="CBC")
            )
            records = MedicalRecordRepository(session)
            await _dated(session, patient.id, cbc, [1], original_filename="Lipid Panel — 2016.json")
            await _dated(
                session, patient.id, cbc, [2], original_filename="x.json", description="Metformin"
            )
            await _dated(session, patient.id, cbc, [3], original_filename="unrelated.json")

            async def find(term: str) -> list[str]:
                rows = await records.list_page(patient_id=patient.id, search=term, limit=10)
                return sorted(row[0].original_filename for row in rows)

            assert await find("lipid") == ["Lipid Panel — 2016.json"]  # case-insensitive
            assert await find("PANEL") == ["Lipid Panel — 2016.json"]
            assert await find("metformin") == ["x.json"]  # description, not filename
            assert await find("nothing-here") == []
            # A record whose description is NULL must not vanish from unrelated searches.
            assert await find("unrelated") == ["unrelated.json"]

    asyncio.run(scenario())


def test_like_metacharacters_in_a_search_term_are_literal() -> None:
    """A patient searching "100_mg" wants that string, not "100" + any character + "mg"."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            patient = await _patient(session)
            cbc = await RecordCategoryRepository(session).add(
                RecordCategory(code="CBC", display_name="CBC")
            )
            records = MedicalRecordRepository(session)
            await _dated(session, patient.id, cbc, [1], original_filename="dose 100_mg.json")
            await _dated(session, patient.id, cbc, [2], original_filename="dose 100Xmg.json")
            await _dated(session, patient.id, cbc, [3], original_filename="saved 50% today.json")
            await _dated(session, patient.id, cbc, [4], original_filename="saved 5099 today.json")

            async def find(term: str) -> list[str]:
                rows = await records.list_page(patient_id=patient.id, search=term, limit=10)
                return sorted(row[0].original_filename for row in rows)

            assert await find("100_mg") == ["dose 100_mg.json"]  # not 100Xmg
            assert await find("50%") == ["saved 50% today.json"]  # not 5099
            # A bare wildcard is a literal too, so it matches nothing rather than everything.
            assert await find("%") == ["saved 50% today.json"]
            assert await find("_") == ["dose 100_mg.json"]

    asyncio.run(scenario())


def test_escape_like_is_ordered_so_the_escape_character_is_not_double_escaped() -> None:
    assert escape_like("plain") == "%plain%"
    assert escape_like("100_mg") == "%100\\_mg%"
    assert escape_like("50%") == "%50\\%%"
    # The backslash is escaped once, not once per metacharacter pass.
    assert escape_like("a\\b") == "%a\\\\b%"


def test_search_sort_and_category_compose() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            patient = await _patient(session)
            categories = RecordCategoryRepository(session)
            cbc = await categories.add(RecordCategory(code="CBC", display_name="CBC"))
            mri = await categories.add(RecordCategory(code="MRI", display_name="MRI"))
            records = MedicalRecordRepository(session)
            await _dated(session, patient.id, cbc, [1, 3], original_filename="panel.json")
            await _dated(session, patient.id, mri, [2], original_filename="panel.json")
            await _dated(session, patient.id, cbc, [4], original_filename="other.json")

            rows = await records.list_page(
                patient_id=patient.id,
                category_id=cbc.id,
                search="panel",
                sort=SortDirection.OLDEST_FIRST,
                limit=10,
            )
            assert [row[0].date_of_service.day for row in rows] == [1, 3]

    asyncio.run(scenario())
