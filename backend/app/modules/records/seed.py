"""Reference-data seeding: the 3 simulated hospitals + the record-category vocabulary,
and (M2) the demo hospital staff — one admin and one doctor per simulated hospital.

Idempotent by construction — insert-if-absent keyed on the business identifiers
(``hid`` / ``code`` / synthetic ``firebase_uid``), so re-running never duplicates and
existing rows (including their UUIDs) are never touched. Demo data is synthetic; the
simulated hospitals are ordinary rows, not special cases (.claude/CONTEXT.md §Glossary,
docs/DOMAIN_MODEL.md §1). Staff users carry ``synthetic:`` provider subjects that can
never authenticate (app/modules/auth/seed.py).
"""

from dataclasses import dataclass
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.domain import Role
from app.modules.auth.seed import get_or_create_synthetic_user
from app.modules.records.models import (
    Doctor,
    DoctorStatus,
    Hospital,
    HospitalAdmin,
    HospitalVerificationStatus,
    RecordCategory,
)
from app.modules.records.repository import (
    DoctorRepository,
    HospitalAdminRepository,
    HospitalRepository,
    RecordCategoryRepository,
)

#: The three simulated hospitals (hid, name, address) — CONTEXT.md §Glossary.
SIMULATED_HOSPITALS: Final[tuple[tuple[str, str, str], ...]] = (
    ("HID-0001", "TMH Jamshedpur", "Jamshedpur, Jharkhand (simulated)"),
    ("HID-0002", "CMC Vellore", "Vellore, Tamil Nadu (simulated)"),
    ("HID-0003", "Apollo Hospitals", "Chennai, Tamil Nadu (simulated)"),
)

#: The record-category controlled vocabulary (code, display name) — DOMAIN_MODEL.md §1.
RECORD_CATEGORIES: Final[tuple[tuple[str, str], ...]] = (
    ("CBC", "Complete Blood Count"),
    ("LAB_REPORT", "Lab Report"),
    ("MRI", "MRI Scan"),
    ("XRAY", "X-Ray"),
    ("CT_SCAN", "CT Scan"),
    ("ULTRASOUND", "Ultrasound"),
    ("PRESCRIPTION", "Prescription"),
    ("DISCHARGE_SUMMARY", "Discharge Summary"),
    ("VACCINATION", "Vaccination Record"),
    ("OTHER", "Other"),
)


#: Demo hospital admins, one per simulated hospital: (firebase_uid, hid, full_name, email).
DEMO_HOSPITAL_ADMINS: Final[tuple[tuple[str, str, str, str], ...]] = (
    (
        "synthetic:hospital-admin:hid-0001",
        "HID-0001",
        "Ravi Prasad (Demo Admin)",
        "admin.tmh@demo.pulseos.test",
    ),
    (
        "synthetic:hospital-admin:hid-0002",
        "HID-0002",
        "Susan Thomas (Demo Admin)",
        "admin.cmc@demo.pulseos.test",
    ),
    (
        "synthetic:hospital-admin:hid-0003",
        "HID-0003",
        "Karthik Rajan (Demo Admin)",
        "admin.apollo@demo.pulseos.test",
    ),
)

#: Demo doctors, one per simulated hospital, seeded ACTIVE (demo-ready, like the
#: hospitals' VERIFIED): (firebase_uid, hid, full_name, specialty, registration, email).
DEMO_DOCTORS: Final[tuple[tuple[str, str, str, str, str, str], ...]] = (
    (
        "synthetic:doctor:hid-0001",
        "HID-0001",
        "Dr. Anjali Verma (Demo)",
        "General Medicine",
        "DEMO-MCI-10001",
        "dr.verma@demo.pulseos.test",
    ),
    (
        "synthetic:doctor:hid-0002",
        "HID-0002",
        "Dr. Thomas George (Demo)",
        "Cardiology",
        "DEMO-MCI-10002",
        "dr.george@demo.pulseos.test",
    ),
    (
        "synthetic:doctor:hid-0003",
        "HID-0003",
        "Dr. Priya Nair (Demo)",
        "Radiology",
        "DEMO-MCI-10003",
        "dr.nair@demo.pulseos.test",
    ),
)


@dataclass(frozen=True, slots=True)
class SeedResult:
    hospitals_created: int
    categories_created: int

    @property
    def total_created(self) -> int:
        return self.hospitals_created + self.categories_created


@dataclass(frozen=True, slots=True)
class StaffSeedResult:
    admins_created: int
    doctors_created: int

    @property
    def total_created(self) -> int:
        return self.admins_created + self.doctors_created


async def seed_reference_data(session: AsyncSession) -> SeedResult:
    """Insert missing reference rows; existing rows are left exactly as they are."""
    hospitals = HospitalRepository(session)
    hospitals_created = 0
    for hid, name, address in SIMULATED_HOSPITALS:
        if await hospitals.get_by_hid(hid) is None:
            await hospitals.add(
                Hospital(
                    hid=hid,
                    name=name,
                    address=address,
                    # Simulated hospitals are demo-ready: pre-verified by design.
                    verification_status=HospitalVerificationStatus.VERIFIED,
                )
            )
            hospitals_created += 1

    categories = RecordCategoryRepository(session)
    categories_created = 0
    for code, display_name in RECORD_CATEGORIES:
        if await categories.get_by_code(code) is None:
            await categories.add(RecordCategory(code=code, display_name=display_name))
            categories_created += 1

    return SeedResult(hospitals_created=hospitals_created, categories_created=categories_created)


async def seed_demo_staff(session: AsyncSession) -> StaffSeedResult:
    """Insert missing demo admins/doctors; existing rows are left exactly as they are.

    Requires the reference hospitals (``seed_reference_data`` runs first); a missing
    hospital is a programming/ordering error, not a seedable condition.
    """
    hospitals = HospitalRepository(session)
    admins = HospitalAdminRepository(session)
    doctors = DoctorRepository(session)

    admins_created = 0
    for firebase_uid, hid, full_name, email in DEMO_HOSPITAL_ADMINS:
        hospital = await _require_hospital(hospitals, hid)
        user, _ = await get_or_create_synthetic_user(
            session, firebase_uid=firebase_uid, role=Role.HOSPITAL_ADMIN, email=email
        )
        if await admins.get_by_user_id(user.id) is None:
            await admins.add(
                HospitalAdmin(user_id=user.id, hospital_id=hospital.id, full_name=full_name)
            )
            admins_created += 1

    doctors_created = 0
    for firebase_uid, hid, full_name, specialty, registration_number, email in DEMO_DOCTORS:
        hospital = await _require_hospital(hospitals, hid)
        user, _ = await get_or_create_synthetic_user(
            session, firebase_uid=firebase_uid, role=Role.DOCTOR, email=email
        )
        if await doctors.get_by_user_id(user.id) is None:
            await doctors.add(
                Doctor(
                    user_id=user.id,
                    hospital_id=hospital.id,
                    full_name=full_name,
                    specialty=specialty,
                    registration_number=registration_number,
                    # Demo doctors are demo-ready: pre-activated by design.
                    status=DoctorStatus.ACTIVE,
                )
            )
            doctors_created += 1

    return StaffSeedResult(admins_created=admins_created, doctors_created=doctors_created)


async def _require_hospital(hospitals: HospitalRepository, hid: str) -> Hospital:
    hospital = await hospitals.get_by_hid(hid)
    if hospital is None:
        raise LookupError(f"hospital {hid} missing — run seed_reference_data first")
    return hospital
