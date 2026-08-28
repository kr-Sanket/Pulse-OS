"""Seed idempotency tests: repeated runs create nothing, change nothing."""

import asyncio
from uuid import UUID

from app.core.db import Base, create_session_factory
from app.modules.records.models import Hospital, HospitalVerificationStatus, RecordCategory
from app.modules.records.seed import (
    RECORD_CATEGORIES,
    SIMULATED_HOSPITALS,
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
                assert first.categories_created == 10
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
                assert len(categories) == 10  # DOMAIN_MODEL vocabulary, nothing invented
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
        "OTHER",
    ]
