"""Patient-directory service — the patients module's interface for other modules.

Module isolation (docs/SYSTEM_ARCHITECTURE.md rule 1): the ``patients`` table is this
module's; other modules resolve patients through this service, never by querying the
table. Lookups return the profile row (or None) — they say nothing about what the caller
may *do* with the patient, which is the authorization layers' job (ADR-013).
"""

from uuid import UUID

from app.modules.patients.models import Patient
from app.modules.patients.repository import PatientRepository


class PatientDirectoryService:
    def __init__(self, patients: PatientRepository) -> None:
        self._patients = patients

    async def get_by_user_id(self, user_id: UUID) -> Patient | None:
        return await self._patients.get_by_user_id(user_id)

    async def get_by_health_id(self, health_id: str) -> Patient | None:
        """Resolve a Health ID as typed at a reception desk: case-insensitive, whitespace
        tolerated (ADR-012 stores canonical uppercase)."""
        return await self._patients.get_by_health_id(health_id.strip().upper())
