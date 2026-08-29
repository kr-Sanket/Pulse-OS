"""Unit tests for simulated hospital and synthetic entity seeding engine."""

import asyncio

from app.core.seed import (
    SIMULATED_HOSPITALS,
    SYNTHETIC_DOCTORS,
    SYNTHETIC_PATIENTS,
    SeedSummary,
    seed_database,
)
from app.modules.auth.domain import Role
from app.modules.auth.repository import UserRepository
from app.modules.doctors.repository import DoctorRepository
from app.modules.hospitals.models import Hospital
from app.modules.hospitals.repository import HospitalRepository
from app.modules.patients.repository import PatientRepository
from app.modules.records.models import DEFAULT_RECORD_CATEGORIES
from app.modules.records.repository import RecordCategoryRepository

from tests.support import sqlite_session


def test_seed_database_creates_all_entities() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            summary = await seed_database(session)

            assert isinstance(summary, SeedSummary)
            assert summary.categories_created == len(DEFAULT_RECORD_CATEGORIES)
            assert summary.hospitals_created == len(SIMULATED_HOSPITALS)
            assert summary.doctors_created == len(SYNTHETIC_DOCTORS)
            assert summary.patients_created == len(SYNTHETIC_PATIENTS)

            # 1. Verify Categories
            cat_repo = RecordCategoryRepository(session)
            all_cats = await cat_repo.list_all()
            assert len(all_cats) == len(DEFAULT_RECORD_CATEGORIES)
            assert await cat_repo.get_by_code("CBC") is not None
            assert await cat_repo.get_by_code("MRI") is not None

            # 2. Verify Hospitals
            hosp_repo = HospitalRepository(session)
            h_tmh = await hosp_repo.get_by_hospital_id("HID-0001")
            assert h_tmh is not None and h_tmh.name == "Tata Main Hospital"

            h_cmc = await hosp_repo.get_by_hospital_id("HID-0002")
            assert h_cmc is not None and h_cmc.name == "Christian Medical College"

            h_apollo = await hosp_repo.get_by_hospital_id("HID-0003")
            assert h_apollo is not None and h_apollo.name == "Apollo Hospitals"

            # 3. Verify Doctors & Roles
            user_repo = UserRepository(session)
            doc_repo = DoctorRepository(session)

            u_tmh = await user_repo.get_by_firebase_uid("dev-doc-tmh")
            assert u_tmh is not None and u_tmh.role is Role.DOCTOR

            doc_tmh = await doc_repo.get_by_registration_number("REG-10001")
            assert doc_tmh is not None
            assert doc_tmh.user_id == u_tmh.id
            assert doc_tmh.hospital_id == h_tmh.id
            assert doc_tmh.specialty == "Cardiology"

            # 4. Verify Patients
            pat_repo = PatientRepository(session)
            u_asha = await user_repo.get_by_firebase_uid("dev-pat-asha")
            assert u_asha is not None and u_asha.role is Role.PATIENT

            pat_asha = await pat_repo.get_by_user_id(u_asha.id)
            assert pat_asha is not None
            assert pat_asha.health_id == "PHI-IND-2026-7K3M99X"
            assert pat_asha.full_name == "Asha Rao"

    asyncio.run(scenario())


def test_seed_database_is_idempotent() -> None:
    """Running seed_database repeatedly must be a safe no-op for existing records."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            # First pass: creates all
            s1 = await seed_database(session)
            assert s1.categories_created == 10
            assert s1.hospitals_created == 3
            assert s1.doctors_created == 3
            assert s1.patients_created == 2

            # Second pass: creates 0
            s2 = await seed_database(session)
            assert s2.categories_created == 0
            assert s2.hospitals_created == 0
            assert s2.doctors_created == 0
            assert s2.patients_created == 0

            # Verify totals remain exact
            all_hosps = await HospitalRepository(session).list_all()
            assert len(all_hosps) == 3

    asyncio.run(scenario())


def test_seed_database_handles_partial_preexisting_data() -> None:
    """If some data already exists, seed_database should populate only the missing entities."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            # Manually pre-create TMH Jamshedpur
            hosp_repo = HospitalRepository(session)
            await hosp_repo.add(
                Hospital(hospital_id="HID-0001", name="Tata Main Hospital", address="Jamshedpur")
            )

            # Run seed
            summary = await seed_database(session)
            assert summary.hospitals_created == 2  # Only CMC and Apollo created

            tmh = await hosp_repo.get_by_hospital_id("HID-0001")
            assert tmh is not None

            # Doctor for TMH still connects to the pre-existing TMH hospital entity
            doc = await DoctorRepository(session).get_by_registration_number("REG-10001")
            assert doc is not None
            assert doc.hospital_id == tmh.id

    asyncio.run(scenario())
