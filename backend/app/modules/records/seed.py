"""Reference-data seeding: the 3 simulated hospitals + the record-category vocabulary.

Idempotent by construction — insert-if-absent keyed on the business identifiers
(``hid`` / ``code``), so re-running never duplicates and existing rows (including their
UUIDs) are never touched. Demo data is synthetic; the simulated hospitals are ordinary
rows, not special cases (.claude/CONTEXT.md §Glossary, docs/DOMAIN_MODEL.md §1).
"""

from dataclasses import dataclass
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.records.models import Hospital, HospitalVerificationStatus, RecordCategory
from app.modules.records.repository import HospitalRepository, RecordCategoryRepository

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


@dataclass(frozen=True, slots=True)
class SeedResult:
    hospitals_created: int
    categories_created: int

    @property
    def total_created(self) -> int:
        return self.hospitals_created + self.categories_created


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
