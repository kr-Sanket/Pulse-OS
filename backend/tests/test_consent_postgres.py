"""PostgreSQL-specific consent behaviour: duplicate guards under real concurrency, the
integrity-error mapping driven by SQLSTATEs, and the filename column boundary.

**Opt-in.** Skipped unless ``PULSEOS_TEST_POSTGRES_URL`` names a PostgreSQL database
(``postgresql+asyncpg://…``) the suite may use. Each test creates its own uniquely named
schema, works only inside it and drops only that schema afterwards; nothing outside it is
read or written. Point it at a scratch database, never at real data.

What SQLite cannot show and these do: two transactions on separate connections racing
check-then-insert, the advisory lock (``ConsentRequestRepository.lock_pair``) serialising
them, PostgreSQL's SQLSTATE-based unique/foreign-key classification, and ``VARCHAR(255)``
counting characters rather than bytes. Each race test has a control run with the lock
disabled, which must produce the duplicate — proof the race window is real and that the
lock, not timing luck, is what prevents it.
"""

import asyncio
import datetime as dt
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.core.db import Base
from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.auth.models import User
from app.modules.consent.dependencies import RecordsStaffDirectory
from app.modules.consent.errors import (
    CategoryAlreadyGrantedError,
    DuplicateDecisionError,
    DuplicateGrantError,
    DuplicatePendingRequestError,
    DuplicateRequestCategoryError,
    UnrequestedCategoryError,
)
from app.modules.consent.models import (
    ConsentDecision,
    ConsentDecisionStatus,
    ConsentGrant,
    ConsentRequest,
    ConsentRequestCategory,
    ConsentRequestStatus,
)
from app.modules.consent.repository import (
    AuditLogRepository,
    ConsentDecisionRepository,
    ConsentGrantRepository,
    ConsentRequestCategoryRepository,
    ConsentRequestRepository,
)
from app.modules.consent.service import ConsentService
from app.modules.notifications.repository import NotificationRepository
from app.modules.patients.directory import PatientDirectoryService
from app.modules.patients.models import Patient
from app.modules.patients.repository import PatientRepository
from app.modules.records.directory import staff_directory
from app.modules.records.models import (
    Doctor,
    DoctorStatus,
    Hospital,
    HospitalVerificationStatus,
    MedicalRecord,
    RecordCategory,
    RecordOrigin,
)
from app.modules.records.service import MAX_FILENAME_LENGTH
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests.support import FakeClinicianDirectory

POSTGRES_URL = os.environ.get("PULSEOS_TEST_POSTGRES_URL", "")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL.startswith("postgresql"),
    reason="PostgreSQL tests are opt-in: set PULSEOS_TEST_POSTGRES_URL to a scratch database",
)

HEALTH_ID = "PHI-IND-2026-1QE8DVR"
#: Concurrent contenders per race. Enough that an unserialised check-then-insert duplicates
#: reliably once the window is widened; small enough to stay well inside the pool.
CONTENDERS = 4
#: How long a contender lingers between its duplicate check and its insert, widening the
#: race window so the control run deterministically interleaves.
RACE_WINDOW_SECONDS = 0.3


@asynccontextmanager
async def _scratch_schema() -> AsyncIterator[AsyncEngine]:
    schema = f"pulseos_consent_{uuid4().hex[:12]}"
    admin = create_async_engine(POSTGRES_URL)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        POSTGRES_URL,
        pool_size=CONTENDERS + 2,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield engine
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


@dataclass(frozen=True)
class World:
    doctor: AuthenticatedUser
    patient: AuthenticatedUser
    clinicians: FakeClinicianDirectory
    patient_id: UUID
    doctor_id: UUID
    hospital_id: UUID
    cbc_id: UUID
    mri_id: UUID


async def _seed(engine: AsyncEngine) -> World:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        doctor_user = User(firebase_uid=f"fb-d-{uuid4()}", role=Role.DOCTOR)
        patient_user = User(firebase_uid=f"fb-p-{uuid4()}", role=Role.PATIENT)
        session.add_all([doctor_user, patient_user])
        hospital = Hospital(
            hid="HID-0001", name="TMH", verification_status=HospitalVerificationStatus.VERIFIED
        )
        session.add(hospital)
        await session.flush()
        doctor = Doctor(
            user_id=doctor_user.id,
            hospital_id=hospital.id,
            full_name="Dr Verma",
            registration_number="R1",
            status=DoctorStatus.ACTIVE,
        )
        patient = Patient(user_id=patient_user.id, health_id=HEALTH_ID, full_name="Aarav")
        cbc = RecordCategory(code="CBC", display_name="CBC")
        mri = RecordCategory(code="MRI", display_name="MRI")
        session.add_all([doctor, patient, cbc, mri])
        await session.flush()
        clinicians = FakeClinicianDirectory()
        clinicians.register(doctor_user.id, doctor_id=doctor.id, hospital_id=hospital.id)
        return World(
            doctor=AuthenticatedUser(
                user_id=doctor_user.id, firebase_uid=doctor_user.firebase_uid, role=Role.DOCTOR
            ),
            patient=AuthenticatedUser(
                user_id=patient_user.id, firebase_uid=patient_user.firebase_uid, role=Role.PATIENT
            ),
            clinicians=clinicians,
            patient_id=patient.id,
            doctor_id=doctor.id,
            hospital_id=hospital.id,
            cbc_id=cbc.id,
            mri_id=mri.id,
        )


def _service(session: AsyncSession, world: World) -> ConsentService:
    return ConsentService(
        requests=ConsentRequestRepository(session),
        request_categories=ConsentRequestCategoryRepository(session),
        decisions=ConsentDecisionRepository(session),
        grants=ConsentGrantRepository(session),
        audit=AuditLogRepository(session),
        patients=PatientDirectoryService(PatientRepository(session)),
        clinicians=world.clinicians,
        staff=RecordsStaffDirectory(staff_directory(session)),
        notifications=NotificationRepository(session),
    )


async def _contend(
    engine: AsyncEngine,
    world: World,
    attempt: Callable[[ConsentService], Awaitable[object]],
) -> list[object]:
    """Run ``CONTENDERS`` attempts at once, each on its own connection and transaction —
    exactly as concurrent HTTP requests would — and collect each result or exception."""
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def one() -> object:
        async with factory() as session, session.begin():
            return await attempt(_service(session, world))

    return list(await asyncio.gather(*(one() for _ in range(CONTENDERS)), return_exceptions=True))


async def _count(engine: AsyncEngine, statement: Any) -> int:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        value = (await session.execute(statement)).scalar_one()
        assert isinstance(value, int)
        return value


def _widen(monkeypatch: pytest.MonkeyPatch, owner: type, method: str) -> None:
    """Make ``owner.method`` linger after it answers, holding the race window open between
    a duplicate check and the insert that follows it."""
    original = getattr(owner, method)

    async def lingering(self: object, *args: Any, **kwargs: Any) -> Any:
        result = await original(self, *args, **kwargs)
        await asyncio.sleep(RACE_WINDOW_SECONDS)
        return result

    monkeypatch.setattr(owner, method, lingering)


def _disable_pair_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_lock(self: object, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(ConsentRequestRepository, "lock_pair", no_lock)


# -- concurrent request creation --------------------------------------------------------


async def _race_creation(engine: AsyncEngine, world: World) -> tuple[list[object], int]:
    async def create(service: ConsentService) -> object:
        return await service.create_request(
            world.doctor, patient_health_id=HEALTH_ID, category_ids=[world.cbc_id], purpose="p"
        )

    outcomes = await _contend(engine, world, create)
    rows = await _count(engine, select(func.count()).select_from(ConsentRequest))
    return outcomes, rows


def test_concurrent_duplicate_requests_create_exactly_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _widen(monkeypatch, ConsentRequestRepository, "open_category_ids")

    async def scenario() -> None:
        async with _scratch_schema() as engine:
            world = await _seed(engine)
            outcomes, rows = await _race_creation(engine, world)

            refused = [o for o in outcomes if isinstance(o, DuplicatePendingRequestError)]
            unexpected = [o for o in outcomes if isinstance(o, BaseException) and o not in refused]
            assert unexpected == []
            assert len(refused) == CONTENDERS - 1
            assert rows == 1

    asyncio.run(scenario())


def test_control_without_the_pair_lock_the_same_race_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The negative control: the race is real, so the lock is what prevents it."""
    _widen(monkeypatch, ConsentRequestRepository, "open_category_ids")
    _disable_pair_lock(monkeypatch)

    async def scenario() -> None:
        async with _scratch_schema() as engine:
            world = await _seed(engine)
            _, rows = await _race_creation(engine, world)
            assert rows > 1

    asyncio.run(scenario())


# -- concurrent approvals ---------------------------------------------------------------


async def _two_open_requests_for_cbc(engine: AsyncEngine, world: World) -> list[UUID]:
    """The legacy state the approval guard exists for: two open requests asking one
    clinician's CBC, written directly (the creation guard would refuse the second)."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ids: list[UUID] = []
    async with factory() as session, session.begin():
        for _ in range(CONTENDERS):
            request = ConsentRequest(
                patient_id=world.patient_id,
                requester_doctor_id=world.doctor_id,
                requester_hospital_id=world.hospital_id,
                purpose="legacy",
                status=ConsentRequestStatus.PENDING,
                expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=7),
            )
            session.add(request)
            await session.flush()
            session.add(ConsentRequestCategory(request_id=request.id, category_id=world.cbc_id))
            ids.append(request.id)
    return ids


async def _race_approvals(engine: AsyncEngine, world: World) -> tuple[list[object], int]:
    request_ids = iter(await _two_open_requests_for_cbc(engine, world))

    async def approve(service: ConsentService) -> object:
        return await service.approve_categories(world.patient, next(request_ids), [world.cbc_id])

    outcomes = await _contend(engine, world, approve)
    active = await _count(
        engine,
        select(func.count())
        .select_from(ConsentGrant)
        .where(
            ConsentGrant.category_id == world.cbc_id,
            ConsentGrant.revoked_at.is_(None),
        ),
    )
    return outcomes, active


def test_concurrent_approvals_leave_exactly_one_active_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _widen(monkeypatch, ConsentGrantRepository, "list_active_category_ids")

    async def scenario() -> None:
        async with _scratch_schema() as engine:
            world = await _seed(engine)
            outcomes, active = await _race_approvals(engine, world)

            refused = [o for o in outcomes if isinstance(o, CategoryAlreadyGrantedError)]
            unexpected = [o for o in outcomes if isinstance(o, BaseException) and o not in refused]
            assert unexpected == []
            assert len(refused) == CONTENDERS - 1
            assert active == 1

    asyncio.run(scenario())


def test_control_without_the_pair_lock_concurrent_approvals_duplicate_grants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _widen(monkeypatch, ConsentGrantRepository, "list_active_category_ids")
    _disable_pair_lock(monkeypatch)

    async def scenario() -> None:
        async with _scratch_schema() as engine:
            world = await _seed(engine)
            _, active = await _race_approvals(engine, world)
            assert active > 1

    asyncio.run(scenario())


# -- integrity-error mapping on real SQLSTATEs ------------------------------------------


def test_unique_violations_map_to_conflicts_and_other_failures_surface_as_themselves() -> None:
    async def scenario() -> None:
        async with _scratch_schema() as engine:
            world = await _seed(engine)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session, session.begin():
                request = ConsentRequest(
                    patient_id=world.patient_id,
                    requester_doctor_id=world.doctor_id,
                    requester_hospital_id=world.hospital_id,
                    purpose="p",
                    status=ConsentRequestStatus.PENDING,
                    expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=7),
                )
                await ConsentRequestRepository(session).add(request)
                categories = ConsentRequestCategoryRepository(session)
                decisions = ConsentDecisionRepository(session)
                grants = ConsentGrantRepository(session)

                await categories.add(
                    ConsentRequestCategory(request_id=request.id, category_id=world.cbc_id)
                )
                # 23505 unique → the domain conflict, each in its own savepoint.
                with pytest.raises(DuplicateRequestCategoryError):
                    await categories.add(
                        ConsentRequestCategory(request_id=request.id, category_id=world.cbc_id)
                    )
                decision = await decisions.add(
                    ConsentDecision(
                        request_id=request.id,
                        category_id=world.cbc_id,
                        status=ConsentDecisionStatus.APPROVED,
                    )
                )
                with pytest.raises(DuplicateDecisionError):
                    await decisions.add(
                        ConsentDecision(
                            request_id=request.id,
                            category_id=world.cbc_id,
                            status=ConsentDecisionStatus.REJECTED,
                        )
                    )
                # The composite foreign key keeps its own meaning.
                with pytest.raises(UnrequestedCategoryError):
                    await decisions.add(
                        ConsentDecision(
                            request_id=request.id,
                            category_id=world.mri_id,
                            status=ConsentDecisionStatus.APPROVED,
                        )
                    )

                def grant(decision_id: UUID) -> ConsentGrant:
                    return ConsentGrant(
                        decision_id=decision_id,
                        patient_id=world.patient_id,
                        grantee_doctor_id=world.doctor_id,
                        category_id=world.cbc_id,
                        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=90),
                    )

                await grants.add(grant(decision.id))
                with pytest.raises(DuplicateGrantError):
                    await grants.add(grant(decision.id))

                # 23503 foreign key → not a duplicate: the raw IntegrityError propagates.
                with pytest.raises(IntegrityError) as missing_decision:
                    await grants.add(grant(uuid4()))
                assert not isinstance(missing_decision.value, DuplicateGrantError)
                assert getattr(missing_decision.value.orig, "sqlstate", None) == "23503"

                with pytest.raises(IntegrityError) as missing_category:
                    await categories.add(
                        ConsentRequestCategory(request_id=request.id, category_id=uuid4())
                    )
                assert getattr(missing_category.value.orig, "sqlstate", None) == "23503"

                # Every refusal was contained in its savepoint; the transaction still works.
                count = await session.execute(select(func.count()).select_from(ConsentGrant))
                assert count.scalar_one() == 1

    asyncio.run(scenario())


# -- the filename column -----------------------------------------------------------------


def test_the_filename_column_holds_255_multibyte_characters_and_refuses_256() -> None:
    """VARCHAR(255) counts characters on PostgreSQL, so the upload limit (255 characters)
    is exactly the column's — a 255-character name of two-byte characters fits."""
    accepted = "é" * (MAX_FILENAME_LENGTH - 4) + ".pdf"
    refused = "é" * (MAX_FILENAME_LENGTH - 3) + ".pdf"
    assert len(accepted) == MAX_FILENAME_LENGTH and len(accepted.encode()) > 255

    async def scenario() -> None:
        async with _scratch_schema() as engine:
            world = await _seed(engine)
            factory = async_sessionmaker(engine, expire_on_commit=False)

            def record(filename: str) -> MedicalRecord:
                return MedicalRecord(
                    patient_id=world.patient_id,
                    category_id=world.cbc_id,
                    origin=RecordOrigin.PATIENT_LOCKER,
                    date_of_service=dt.date(2026, 3, 1),
                    original_filename=filename,
                    content_type="application/pdf",
                    size_bytes=1,
                    s3_key=f"records/{world.patient_id}/{uuid4()}",
                )

            async with factory() as session, session.begin():
                stored = record(accepted)
                session.add(stored)
                await session.flush()
                stored_id = stored.id
            async with factory() as session:
                round_trip = await session.get(MedicalRecord, stored_id)
                assert round_trip is not None
                assert round_trip.original_filename == accepted

            # One character more is what the boundary check exists to keep away from here.
            with pytest.raises(DBAPIError) as too_long:
                async with factory() as session, session.begin():
                    session.add(record(refused))
                    await session.flush()
            assert getattr(too_long.value.orig, "sqlstate", None) == "22001"

    asyncio.run(scenario())
