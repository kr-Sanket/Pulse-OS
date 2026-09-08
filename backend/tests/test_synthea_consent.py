"""Consent enforcement over *imported* Synthea records.

The report's central safety claim was that imported records need no import-specific
authorization code, because ``consent.enforce`` keys on ``(patient_id, category_id)`` and
never inspects ``origin``. That is a claim about behaviour, so it is tested against records
that actually came out of the importer rather than against hand-built rows.

The fear this file exists to disprove: that ~900 imported records become readable by any
clinician merely by existing in the database.
"""

import asyncio
import datetime as dt
from pathlib import Path
from uuid import UUID

import pytest
from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.auth.models import User
from app.modules.consent.dependencies import RecordsStaffDirectory
from app.modules.consent.errors import AccessDeniedError
from app.modules.consent.models import AuditAction
from app.modules.consent.repository import (
    AuditLogRepository,
    ConsentDecisionRepository,
    ConsentGrantRepository,
    ConsentRequestCategoryRepository,
    ConsentRequestRepository,
)
from app.modules.consent.service import ConsentService
from app.modules.patients.directory import PatientDirectoryService
from app.modules.patients.repository import PatientRepository
from app.modules.records.directory import staff_directory
from app.modules.records.fake import FakeObjectStorage
from app.modules.records.fhir_import import RosterEntry, SyntheaImporter
from app.modules.records.models import (
    Doctor,
    DoctorStatus,
    Hospital,
    HospitalVerificationStatus,
    MedicalRecord,
    RecordCategory,
)
from app.modules.records.seed import seed_reference_data
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import FakeClinicianDirectory, sqlite_session

FIXTURES = Path(__file__).parent / "fixtures" / "fhir"

FIXTURE_ENTRY = RosterEntry(
    filename="canonical.json",
    synthea_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
    health_id="PHI-IND-2026-J0TA0DK",
    email="fixture999@synthea.pulseos.test",
    expected_name="Fixture999 Testcase999",
)


class Clock:
    def __init__(self, now: dt.datetime) -> None:
        self.now = now

    def __call__(self) -> dt.datetime:
        return self.now


class Scenario:
    """An imported patient, a clinician at a verified hospital, and a real ConsentService."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build(self) -> "Scenario":
        await seed_reference_data(self.session)
        self.storage = FakeObjectStorage()
        await SyntheaImporter(self.session, storage=self.storage).import_bundle(
            FIXTURE_ENTRY, (FIXTURES / "canonical.json").read_bytes()
        )

        patients = PatientRepository(self.session)
        imported = await patients.get_by_health_id(FIXTURE_ENTRY.health_id)
        assert imported is not None
        self.patient_id = imported.id

        doctor_user = User(firebase_uid="fb-doctor-synthea", role=Role.DOCTOR)
        self.session.add(doctor_user)
        hospital = Hospital(
            hid="HID-0009",
            name="Test Hospital",
            verification_status=HospitalVerificationStatus.VERIFIED,
        )
        self.session.add(hospital)
        await self.session.flush()
        doctor = Doctor(
            user_id=doctor_user.id,
            hospital_id=hospital.id,
            full_name="Dr Synthea",
            registration_number="R-SYN",
            status=DoctorStatus.ACTIVE,
        )
        self.session.add(doctor)
        await self.session.flush()

        clinicians = FakeClinicianDirectory()
        clinicians.register(doctor_user.id, doctor_id=doctor.id, hospital_id=hospital.id)
        self.clock = Clock(dt.datetime(2026, 9, 7, 12, 0, tzinfo=dt.UTC))
        self.service = ConsentService(
            requests=ConsentRequestRepository(self.session),
            request_categories=ConsentRequestCategoryRepository(self.session),
            decisions=ConsentDecisionRepository(self.session),
            grants=ConsentGrantRepository(self.session),
            audit=AuditLogRepository(self.session),
            patients=PatientDirectoryService(patients),
            clinicians=clinicians,
            staff=RecordsStaffDirectory(staff_directory(self.session)),
            clock=self.clock,
        )
        self.audit = AuditLogRepository(self.session)
        self.doctor = AuthenticatedUser(
            user_id=doctor_user.id, firebase_uid=doctor_user.firebase_uid, role=Role.DOCTOR
        )
        self.patient = AuthenticatedUser(
            user_id=imported.user_id, firebase_uid="fb-patient-synthea", role=Role.PATIENT
        )
        self.categories = {
            category.code: category.id
            for category in (await self.session.execute(select(RecordCategory))).scalars()
        }
        return self

    async def records_in(self, code: str) -> list[MedicalRecord]:
        result = await self.session.execute(
            select(MedicalRecord).where(
                MedicalRecord.patient_id == self.patient_id,
                MedicalRecord.category_id == self.categories[code],
            )
        )
        return list(result.scalars())

    async def reads(self, code: str) -> bool:
        record = (await self.records_in(code))[0]
        try:
            await self.service.enforce(
                self.doctor,
                patient_id=self.patient_id,
                category_id=self.categories[code],
                action=AuditAction.RECORD_VIEWED,
                record_id=record.id,
            )
            return True
        except AccessDeniedError:
            return False

    async def grant(self, *codes: str) -> UUID:
        view = await self.service.create_request(
            self.doctor,
            patient_health_id=FIXTURE_ENTRY.health_id,
            category_ids=[self.categories[code] for code in codes],
            purpose="follow-up",
        )
        outcome = await self.service.approve_categories(
            self.patient, view.request.id, [self.categories[code] for code in codes]
        )
        return outcome.grants[0].id

    async def actions(self) -> list[str]:
        rows = await self.audit.list_page_by_patient(self.patient_id, after=None, limit=99)
        return sorted(row.action.value for row in rows)


async def _scenario(session: AsyncSession) -> Scenario:
    return await Scenario(session).build()


# -- the default posture ---------------------------------------------------------------


def test_a_clinician_with_no_grant_can_read_no_imported_record() -> None:
    """The whole point. ~900 imported rows must not be readable merely by existing."""

    async def run() -> None:
        async with sqlite_session() as session:
            s = await _scenario(session)
            for code in ("CONDITION", "PRESCRIPTION", "LAB_REPORT", "CBC", "ALLERGY"):
                assert await s.reads(code) is False

    asyncio.run(run())


def test_a_refused_read_of_an_imported_record_is_audited() -> None:
    async def run() -> None:
        async with sqlite_session() as session:
            s = await _scenario(session)
            await s.reads("CONDITION")
            assert AuditAction.ACCESS_DENIED.value in await s.actions()

    asyncio.run(run())


def test_the_owning_patient_reads_their_imported_records() -> None:
    async def run() -> None:
        async with sqlite_session() as session:
            s = await _scenario(session)
            record = (await s.records_in("CONDITION"))[0]
            await s.service.enforce(
                s.patient,
                patient_id=s.patient_id,
                category_id=s.categories["CONDITION"],
                action=AuditAction.RECORD_VIEWED,
                record_id=record.id,
            )
            assert AuditAction.RECORD_VIEWED.value in await s.actions()

    asyncio.run(run())


# -- granted access is category-scoped ------------------------------------------------


def test_a_grant_opens_only_the_categories_it_names() -> None:
    """The demo's payoff and its safety property at once: granting the condition list must
    not disclose the lab results."""

    async def run() -> None:
        async with sqlite_session() as session:
            s = await _scenario(session)
            await s.grant("CONDITION")
            assert await s.reads("CONDITION") is True
            assert await s.reads("LAB_REPORT") is False
            assert await s.reads("PRESCRIPTION") is False

    asyncio.run(run())


def test_the_listing_scope_matches_what_enforcement_would_admit() -> None:
    """``granted_category_ids`` filters a clinician's listing; if it disagreed with
    ``enforce`` a record could be listed and then refused."""

    async def run() -> None:
        async with sqlite_session() as session:
            s = await _scenario(session)
            await s.grant("CONDITION", "PRESCRIPTION")
            scope = await s.service.granted_category_ids(
                s.doctor, patient_id=s.patient_id, at=s.clock.now
            )
            assert scope == {s.categories["CONDITION"], s.categories["PRESCRIPTION"]}
            for code in ("CONDITION", "PRESCRIPTION"):
                assert await s.reads(code) is True
            for code in ("LAB_REPORT", "CBC", "ALLERGY", "VACCINATION"):
                assert await s.reads(code) is False

    asyncio.run(run())


def test_revocation_closes_access_to_imported_records() -> None:
    async def run() -> None:
        async with sqlite_session() as session:
            s = await _scenario(session)
            grant_id = await s.grant("CONDITION")
            assert await s.reads("CONDITION") is True
            await s.service.revoke_grant(s.patient, grant_id)
            assert await s.reads("CONDITION") is False

    asyncio.run(run())


def test_a_patient_cannot_reach_another_patients_imported_records() -> None:
    """Patient isolation survives the import: ownership, not a grant, is the patient's
    route, and it is checked against the record's own patient."""

    async def run() -> None:
        async with sqlite_session() as session:
            s = await _scenario(session)
            intruder = AuthenticatedUser(
                user_id=s.doctor.user_id, firebase_uid="fb-other", role=Role.PATIENT
            )
            with pytest.raises(AccessDeniedError):
                await s.service.enforce(
                    intruder,
                    patient_id=s.patient_id,
                    category_id=s.categories["CONDITION"],
                    action=AuditAction.RECORD_VIEWED,
                    record_id=(await s.records_in("CONDITION"))[0].id,
                )

    asyncio.run(run())


# -- the patient's own controls still apply -------------------------------------------


def test_hiding_an_imported_record_removes_it_from_the_existence_projection() -> None:
    """``is_hidden`` is enforced on the discovery path too: a hidden record must not exist
    as far as anyone but its owner is concerned."""

    async def run() -> None:
        from app.modules.records.repository import MedicalRecordRepository

        async with sqlite_session() as session:
            s = await _scenario(session)
            records = MedicalRecordRepository(session)
            before = set(await records.list_category_ids_with_records(s.patient_id))
            assert s.categories["ALLERGY"] in before

            for record in await s.records_in("ALLERGY"):
                record.is_hidden = True
            await session.flush()

            after = set(await records.list_category_ids_with_records(s.patient_id))
            assert s.categories["ALLERGY"] not in after
            assert after == before - {s.categories["ALLERGY"]}

    asyncio.run(run())
