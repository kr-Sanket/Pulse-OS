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
)
from app.shared.pagination import CursorKey
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
) -> MedicalRecord:
    record = MedicalRecord(
        patient_id=patient_id,
        category_id=category.id,
        origin=RecordOrigin.HOSPITAL_UPLOAD if hospital_id else RecordOrigin.PATIENT_LOCKER,
        uploaded_by_hospital_id=hospital_id,
        date_of_service=date(2026, 1, 1),
        original_filename="r.pdf",
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
            for second, category in enumerate([cbc, cbc, mri]):
                await _record(
                    session,
                    patient_id=patient.id,
                    category=category,
                    hospital_id=hospital.id,
                    created_at=datetime(2026, 2, 1, 10, 0, second),
                )
            await _record(
                session,
                patient_id=other_patient.id,
                category=cbc,
                hospital_id=None,
                created_at=datetime(2026, 2, 1, 11, 0, 0),
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
                after=CursorKey(created_at=last.created_at, item_id=last.id),
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
