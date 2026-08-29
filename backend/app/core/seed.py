"""Simulated hospital and synthetic entity seeding engine (M0.3 / M2).

Seeds the 3 documented simulated hospitals (docs/PROJECT_OVERVIEW.md §5, .claude/CONTEXT.md):
1. TMH Jamshedpur (HID-0001)
2. CMC Vellore (HID-0002)
3. Apollo Hospitals (HID-0003)

Along with controlled record categories, synthetic clinicians, and synthetic patients.
Fully idempotent: running repeatedly is a safe no-op for existing records.
"""

import logging
from dataclasses import dataclass
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.domain import Role
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.doctors.models import Doctor
from app.modules.doctors.repository import DoctorRepository
from app.modules.hospitals.models import Hospital
from app.modules.hospitals.repository import HospitalRepository
from app.modules.patients.models import Patient
from app.modules.patients.repository import PatientRepository
from app.modules.records.models import DEFAULT_RECORD_CATEGORIES, RecordCategory
from app.modules.records.repository import RecordCategoryRepository

logger = logging.getLogger("pulseos.seed")

# --- Canonical Synthetic Seed Datasets ---

SIMULATED_HOSPITALS: Final[tuple[tuple[str, str, str], ...]] = (
    ("HID-0001", "Tata Main Hospital", "Jamshedpur"),
    ("HID-0002", "Christian Medical College", "Vellore"),
    ("HID-0003", "Apollo Hospitals", "Chennai"),
)

SYNTHETIC_DOCTORS: Final[tuple[tuple[str, str, str, str, str], ...]] = (
    # (firebase_uid, hospital_id, full_name, registration_number, specialty)
    ("dev-doc-tmh", "HID-0001", "Dr. Rajesh Sharma", "REG-10001", "Cardiology"),
    ("dev-doc-cmc", "HID-0002", "Dr. Priya Nair", "REG-20001", "Neurology"),
    ("dev-doc-apollo", "HID-0003", "Dr. Anand Verma", "REG-30001", "General Medicine"),
)

SYNTHETIC_PATIENTS: Final[tuple[tuple[str, str, str], ...]] = (
    # (firebase_uid, health_id, full_name)
    ("dev-pat-asha", "PHI-IND-2026-7K3M99X", "Asha Rao"),
    ("dev-pat-suresh", "PHI-IND-2026-TNE7WRA", "Suresh Kumar"),
)


@dataclass(frozen=True)
class SeedSummary:
    categories_created: int
    hospitals_created: int
    doctors_created: int
    patients_created: int


async def seed_database(session: AsyncSession) -> SeedSummary:
    """Idempotently populate database with categories, 3 hospitals, doctors, and patients."""
    cat_repo = RecordCategoryRepository(session)
    hosp_repo = HospitalRepository(session)
    user_repo = UserRepository(session)
    doc_repo = DoctorRepository(session)
    pat_repo = PatientRepository(session)

    # 1. Seed Categories
    categories_created = 0
    for code, display_name, description in DEFAULT_RECORD_CATEGORIES:
        existing = await cat_repo.get_by_code(code)
        if existing is None:
            await cat_repo.add(
                RecordCategory(code=code, display_name=display_name, description=description)
            )
            categories_created += 1

    # 2. Seed Hospitals
    hospitals_created = 0
    hosp_map: dict[str, Hospital] = {}
    for hid, name, address in SIMULATED_HOSPITALS:
        existing_hosp = await hosp_repo.get_by_hospital_id(hid)
        if existing_hosp is None:
            existing_hosp = await hosp_repo.add(
                Hospital(hospital_id=hid, name=name, address=address)
            )
            hospitals_created += 1
        hosp_map[hid] = existing_hosp

    # 3. Seed Doctors
    doctors_created = 0
    for fb_uid, hid, full_name, reg_num, specialty in SYNTHETIC_DOCTORS:
        hospital = hosp_map[hid]
        # Ensure user account exists
        user = await user_repo.get_by_firebase_uid(fb_uid)
        if user is None:
            user = await user_repo.add(User(firebase_uid=fb_uid, role=Role.DOCTOR))

        # Ensure doctor profile exists
        existing_doc = await doc_repo.get_by_user_id(user.id)
        if existing_doc is None:
            await doc_repo.add(
                Doctor(
                    user_id=user.id,
                    hospital_id=hospital.id,
                    full_name=full_name,
                    registration_number=reg_num,
                    specialty=specialty,
                )
            )
            doctors_created += 1

    # 4. Seed Patients
    patients_created = 0
    for fb_uid, health_id, full_name in SYNTHETIC_PATIENTS:
        user = await user_repo.get_by_firebase_uid(fb_uid)
        if user is None:
            user = await user_repo.add(User(firebase_uid=fb_uid, role=Role.PATIENT))

        existing_pat = await pat_repo.get_by_user_id(user.id)
        if existing_pat is None:
            await pat_repo.add(
                Patient(
                    user_id=user.id,
                    health_id=health_id,
                    full_name=full_name,
                )
            )
            patients_created += 1

    logger.info(
        "Seeding complete: %d categories, %d hospitals, %d doctors, %d patients created.",
        categories_created,
        hospitals_created,
        doctors_created,
        patients_created,
    )

    return SeedSummary(
        categories_created=categories_created,
        hospitals_created=hospitals_created,
        doctors_created=doctors_created,
        patients_created=patients_created,
    )
