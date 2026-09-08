"""Seed idempotency tests: repeated runs create nothing, change nothing."""

import asyncio
from uuid import UUID

import pytest
from app.core.db import Base, create_session_factory
from app.modules.auth.domain import Role
from app.modules.auth.models import User
from app.modules.auth.seed import get_or_create_synthetic_user
from app.modules.patients.health_id import is_valid_health_id
from app.modules.patients.models import Patient
from app.modules.patients.seed import SYNTHETIC_PATIENTS, seed_synthetic_patients
from app.modules.records.models import (
    Doctor,
    DoctorStatus,
    Hospital,
    HospitalAdmin,
    HospitalVerificationStatus,
    RecordCategory,
)
from app.modules.records.seed import (
    RECORD_CATEGORIES,
    SIMULATED_HOSPITALS,
    seed_demo_staff,
    seed_reference_data,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import create_sqlite_test_engine


async def _snapshot(session: AsyncSession) -> tuple[dict[str, UUID], dict[str, UUID]]:
    hospitals = {h.hid: h.id for h in (await session.execute(select(Hospital))).scalars()}
    categories = {c.code: c.id for c in (await session.execute(select(RecordCategory))).scalars()}
    return hospitals, categories


def test_seed_is_idempotent_across_runs_and_sessions() -> None:
    async def scenario() -> None:
        engine = create_sqlite_test_engine()
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            factory = create_session_factory(engine)

            # First run inserts everything (each run in its own session, like the script).
            async with factory() as session, session.begin():
                first = await seed_reference_data(session)
                assert first.hospitals_created == 3
                assert first.categories_created == 13
                first_hospitals, first_categories = await _snapshot(session)

            # Ten further runs insert nothing.
            for _ in range(10):
                async with factory() as session, session.begin():
                    rerun = await seed_reference_data(session)
                    assert rerun.total_created == 0

            # Counts AND row identities (UUIDs) are stable.
            async with factory() as session:
                hospitals, categories = await _snapshot(session)
                assert hospitals == first_hospitals
                assert categories == first_categories
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_seed_creates_exactly_the_documented_reference_data() -> None:
    async def scenario() -> None:
        engine = create_sqlite_test_engine()
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            factory = create_session_factory(engine)
            async with factory() as session, session.begin():
                await seed_reference_data(session)

                hospitals = (await session.execute(select(Hospital))).scalars().all()
                by_hid = {h.hid: h for h in hospitals}
                assert set(by_hid) == {"HID-0001", "HID-0002", "HID-0003"}
                assert by_hid["HID-0001"].name == "TMH Jamshedpur"
                assert by_hid["HID-0002"].name == "CMC Vellore"
                assert by_hid["HID-0003"].name == "Apollo Hospitals"
                assert all(
                    h.verification_status is HospitalVerificationStatus.VERIFIED for h in hospitals
                )

                categories = (await session.execute(select(RecordCategory))).scalars().all()
                assert {c.code for c in categories} == {code for code, _ in RECORD_CATEGORIES}
                assert (
                    len(categories) == 13
                )  # DOMAIN_MODEL vocabulary + the 3 Synthea clinical codes
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_seed_backfills_missing_rows_without_touching_existing_ones() -> None:
    async def scenario() -> None:
        engine = create_sqlite_test_engine()
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            factory = create_session_factory(engine)

            # Pre-create ONE hospital with a custom name (an operator-modified row).
            async with factory() as session, session.begin():
                session.add(
                    Hospital(
                        hid="HID-0002",
                        name="CMC Vellore (renamed)",
                        verification_status=HospitalVerificationStatus.PENDING,
                    )
                )

            async with factory() as session, session.begin():
                result = await seed_reference_data(session)
                assert result.hospitals_created == 2  # only the missing two
                existing = (
                    await session.execute(select(Hospital).where(Hospital.hid == "HID-0002"))
                ).scalar_one()
                # Seed never overwrites what is already there.
                assert existing.name == "CMC Vellore (renamed)"
                assert existing.verification_status is HospitalVerificationStatus.PENDING
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_full_seed_is_idempotent_including_demo_actors() -> None:
    async def scenario() -> None:
        engine = create_sqlite_test_engine()
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            factory = create_session_factory(engine)

            async with factory() as session, session.begin():
                await seed_reference_data(session)
                staff = await seed_demo_staff(session)
                patients_created = await seed_synthetic_patients(session)
                assert staff.admins_created == 3
                assert staff.doctors_created == 3
                assert patients_created == 3
                first_users = {
                    u.firebase_uid: u.id for u in (await session.execute(select(User))).scalars()
                }

            for _ in range(3):
                async with factory() as session, session.begin():
                    await seed_reference_data(session)
                    rerun_staff = await seed_demo_staff(session)
                    rerun_patients = await seed_synthetic_patients(session)
                    assert rerun_staff.total_created == 0
                    assert rerun_patients == 0

            async with factory() as session:
                users = {
                    u.firebase_uid: u.id for u in (await session.execute(select(User))).scalars()
                }
                assert users == first_users  # stable identities across runs
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_demo_staff_are_wired_to_the_right_hospitals_and_states() -> None:
    async def scenario() -> None:
        engine = create_sqlite_test_engine()
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            factory = create_session_factory(engine)
            async with factory() as session, session.begin():
                await seed_reference_data(session)
                await seed_demo_staff(session)

                hospitals = {
                    h.id: h.hid for h in (await session.execute(select(Hospital))).scalars()
                }
                users = {u.id: u for u in (await session.execute(select(User))).scalars()}

                admins = (await session.execute(select(HospitalAdmin))).scalars().all()
                assert {hospitals[a.hospital_id] for a in admins} == {
                    "HID-0001",
                    "HID-0002",
                    "HID-0003",
                }
                assert all(users[a.user_id].role is Role.HOSPITAL_ADMIN for a in admins)

                doctors = (await session.execute(select(Doctor))).scalars().all()
                assert {hospitals[d.hospital_id] for d in doctors} == {
                    "HID-0001",
                    "HID-0002",
                    "HID-0003",
                }
                # Demo doctors are demo-ready (ACTIVE), like the hospitals are VERIFIED.
                assert all(d.status is DoctorStatus.ACTIVE for d in doctors)
                assert all(users[d.user_id].role is Role.DOCTOR for d in doctors)
                # Every seeded identity is clearly synthetic and can never log in.
                assert all(users[a.user_id].firebase_uid.startswith("synthetic:") for a in admins)
                assert all(users[d.user_id].firebase_uid.startswith("synthetic:") for d in doctors)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_demo_staff_require_reference_data_first() -> None:
    async def scenario() -> None:
        engine = create_sqlite_test_engine()
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            factory = create_session_factory(engine)
            async with factory() as session, session.begin():
                with pytest.raises(LookupError, match="seed_reference_data"):
                    await seed_demo_staff(session)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_synthetic_patients_have_pinned_valid_health_ids() -> None:
    async def scenario() -> None:
        engine = create_sqlite_test_engine()
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            factory = create_session_factory(engine)
            async with factory() as session, session.begin():
                await seed_synthetic_patients(session)
                patients = (await session.execute(select(Patient))).scalars().all()
                assert {p.health_id for p in patients} == {
                    health_id for _, health_id, *_ in SYNTHETIC_PATIENTS
                }
                assert all(is_valid_health_id(p.health_id) for p in patients)
                assert all("(Demo)" in p.full_name for p in patients)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_synthetic_user_helper_refuses_real_looking_subjects() -> None:
    async def scenario() -> None:
        engine = create_sqlite_test_engine()
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            factory = create_session_factory(engine)
            async with factory() as session, session.begin():
                with pytest.raises(ValueError, match="synthetic"):
                    await get_or_create_synthetic_user(
                        session, firebase_uid="real-firebase-uid", role=Role.PATIENT
                    )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_documented_constants_match_the_specification() -> None:
    assert [hid for hid, _, _ in SIMULATED_HOSPITALS] == ["HID-0001", "HID-0002", "HID-0003"]
    assert [code for code, _ in RECORD_CATEGORIES] == [
        "CBC",
        "LAB_REPORT",
        "MRI",
        "XRAY",
        "CT_SCAN",
        "ULTRASOUND",
        "PRESCRIPTION",
        "DISCHARGE_SUMMARY",
        "VACCINATION",
        "CONDITION",
        "PROCEDURE",
        "ALLERGY",
        "OTHER",
    ]
