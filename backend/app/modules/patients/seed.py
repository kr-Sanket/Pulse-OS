"""Synthetic demo patients (M2 seed scope — ROADMAP: "3 simulated hospitals + synthetic
patients").

Idempotent by construction — insert-if-absent keyed on the Health ID (and the synthetic
``firebase_uid`` for the identity row). The Health IDs are pinned, genuinely valid
ADR-012 IDs (check character verified by test) so demos and docs can reference them
stably. Synthetic users can never authenticate (app/modules/auth/seed.py).
"""

from datetime import date
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.domain import Role
from app.modules.auth.seed import get_or_create_synthetic_user
from app.modules.patients.models import Gender, Patient
from app.modules.patients.repository import PatientRepository

#: (firebase_uid, health_id, full_name, date_of_birth, gender, email)
SYNTHETIC_PATIENTS: Final[tuple[tuple[str, str, str, date, Gender, str], ...]] = (
    (
        "synthetic:patient:aarav",
        "PHI-IND-2026-1QE8DVR",
        "Aarav Sharma (Demo)",
        date(1988, 3, 14),
        Gender.MALE,
        "aarav@demo.pulseos.test",
    ),
    (
        "synthetic:patient:meera",
        "PHI-IND-2026-5WD2FD4",
        "Meera Krishnan (Demo)",
        date(1995, 11, 2),
        Gender.FEMALE,
        "meera@demo.pulseos.test",
    ),
    (
        "synthetic:patient:joseph",
        "PHI-IND-2026-AES1W87",
        "Joseph Mathew (Demo)",
        date(1972, 7, 30),
        Gender.MALE,
        "joseph@demo.pulseos.test",
    ),
)


async def seed_synthetic_patients(session: AsyncSession) -> int:
    """Insert missing synthetic patients; existing rows are left exactly as they are.
    Returns the number of patient rows created."""
    patients = PatientRepository(session)
    created = 0
    for firebase_uid, health_id, full_name, date_of_birth, gender, email in SYNTHETIC_PATIENTS:
        if await patients.get_by_health_id(health_id) is not None:
            continue
        user, _ = await get_or_create_synthetic_user(
            session, firebase_uid=firebase_uid, role=Role.PATIENT, email=email
        )
        await patients.add(
            Patient(
                user_id=user.id,
                health_id=health_id,
                full_name=full_name,
                date_of_birth=date_of_birth,
                gender=gender,
            )
        )
        created += 1
    return created
