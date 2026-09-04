"""StaffDirectoryService: the patient-facing identity projection published by ``records``.

Two properties matter here and are asserted directly rather than inferred. **What it
exposes** — three display fields, no identifiers, no employment status — because this is
the seam through which staff data reaches a patient's screen. **What it costs** — a fixed
number of statements per page, not one per row, because every consent listing calls it with
a whole page of ids.
"""

import asyncio
import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.core.db import Base
from app.modules.auth.domain import Role
from app.modules.auth.models import User
from app.modules.records.directory import StaffDirectoryService, StaffDisplay, staff_directory
from app.modules.records.models import (
    Doctor,
    DoctorStatus,
    Hospital,
    HospitalAdmin,
    HospitalVerificationStatus,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.support import counting_statements, create_sqlite_test_engine


@dataclass
class Fixture:
    directory: StaffDirectoryService
    doctor_ids: list[UUID]
    doctor_user_ids: list[UUID]
    admin_user_id: UUID
    hospital_id: UUID
    other_hospital_id: UUID


@asynccontextmanager
async def _fixture(*, doctors: int = 2) -> AsyncIterator[tuple[Fixture, AsyncEngine]]:
    """A session over a schema holding ``doctors`` clinicians, one admin, two hospitals."""
    engine = create_sqlite_test_engine()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session, session.begin():
            yield await _arrange(session, doctors=doctors), engine
    finally:
        await engine.dispose()


async def _arrange(session: AsyncSession, *, doctors: int) -> Fixture:
    hospital = Hospital(
        hid="HID-0001",
        name="TMH Jamshedpur",
        verification_status=HospitalVerificationStatus.VERIFIED,
    )
    other = Hospital(
        hid="HID-0002", name="CMC Vellore", verification_status=HospitalVerificationStatus.VERIFIED
    )
    session.add_all([hospital, other])
    await session.flush()

    doctor_rows: list[Doctor] = []
    for index in range(doctors):
        user = User(firebase_uid=f"fb-d-{index}-{uuid4()}", role=Role.DOCTOR)
        session.add(user)
        await session.flush()
        doctor_rows.append(
            Doctor(
                user_id=user.id,
                hospital_id=hospital.id if index % 2 == 0 else other.id,
                full_name=f"Dr Number {index}",
                specialty="Cardiology" if index == 0 else None,
                registration_number=f"R{index}",
                status=DoctorStatus.ACTIVE,
            )
        )
    admin_user = User(firebase_uid=f"fb-a-{uuid4()}", role=Role.HOSPITAL_ADMIN)
    session.add(admin_user)
    await session.flush()
    admin = HospitalAdmin(user_id=admin_user.id, hospital_id=hospital.id, full_name="Rina Admin")
    session.add_all([*doctor_rows, admin])
    await session.flush()

    return Fixture(
        directory=staff_directory(session),
        doctor_ids=[doctor.id for doctor in doctor_rows],
        doctor_user_ids=[doctor.user_id for doctor in doctor_rows],
        admin_user_id=admin_user.id,
        hospital_id=hospital.id,
        other_hospital_id=other.id,
    )


def test_the_projection_carries_display_fields_and_nothing_else() -> None:
    """A structural guard: this dataclass is what reaches a patient, so it must not grow
    an id, a registration number or a status without someone deciding to."""
    assert {field.name for field in dataclasses.fields(StaffDisplay)} == {
        "full_name",
        "specialty",
        "hospital_name",
    }


def test_clinicians_resolve_by_their_own_id_with_the_hospital_they_practise_at() -> None:
    async def scenario() -> None:
        async with _fixture() as (f, _engine):
            displays = await f.directory.clinicians_by_id(f.doctor_ids)

            assert displays[f.doctor_ids[0]] == StaffDisplay(
                full_name="Dr Number 0", specialty="Cardiology", hospital_name="TMH Jamshedpur"
            )
            assert displays[f.doctor_ids[1]] == StaffDisplay(
                full_name="Dr Number 1", specialty=None, hospital_name="CMC Vellore"
            )

    asyncio.run(scenario())


def test_staff_resolve_by_account_id_whether_clinician_or_administrator() -> None:
    """Both kinds appear in a patient's trail: a doctor reading, an admin uploading."""

    async def scenario() -> None:
        async with _fixture() as (f, _engine):
            displays = await f.directory.staff_by_user_id([*f.doctor_user_ids, f.admin_user_id])

            assert displays[f.doctor_user_ids[0]].full_name == "Dr Number 0"
            assert displays[f.admin_user_id] == StaffDisplay(
                full_name="Rina Admin", specialty=None, hospital_name="TMH Jamshedpur"
            )

    asyncio.run(scenario())


def test_an_id_that_resolves_to_nothing_is_simply_absent() -> None:
    """Callers render what they got; a listing must never fail over a missing name."""

    async def scenario() -> None:
        async with _fixture() as (f, _engine):
            unknown = uuid4()

            assert await f.directory.clinicians_by_id([unknown]) == {}
            assert await f.directory.staff_by_user_id([unknown]) == {}
            assert await f.directory.hospital_names([unknown]) == {}

    asyncio.run(scenario())


def test_hospitals_resolve_to_their_display_name() -> None:
    async def scenario() -> None:
        async with _fixture() as (f, _engine):
            names = await f.directory.hospital_names([f.hospital_id, f.other_hospital_id])

            assert names == {f.hospital_id: "TMH Jamshedpur", f.other_hospital_id: "CMC Vellore"}

    asyncio.run(scenario())


def test_resolving_a_page_costs_one_statement_per_kind_not_one_per_row() -> None:
    """The N+1 guard. Ten clinicians resolve in a single SELECT; the actor lookup spans two
    tables and so costs two, whatever the page holds."""

    async def scenario() -> None:
        async with _fixture(doctors=10) as (f, engine):
            with counting_statements(engine) as statements:
                await f.directory.clinicians_by_id(f.doctor_ids)
            assert len(statements) == 1

            with counting_statements(engine) as statements:
                await f.directory.staff_by_user_id([*f.doctor_user_ids, f.admin_user_id])
            assert len(statements) == 2

            with counting_statements(engine) as statements:
                await f.directory.hospital_names([f.hospital_id, f.other_hospital_id])
            assert len(statements) == 1

    asyncio.run(scenario())


def test_resolving_nothing_touches_the_database_at_all() -> None:
    async def scenario() -> None:
        async with _fixture() as (f, engine):
            with counting_statements(engine) as statements:
                assert await f.directory.clinicians_by_id([]) == {}
                assert await f.directory.staff_by_user_id([]) == {}
                assert await f.directory.hospital_names([]) == {}
            assert statements == []

    asyncio.run(scenario())
