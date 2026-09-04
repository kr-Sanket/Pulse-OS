"""Patient-directory service — the patients module's interface for other modules.

Module isolation (docs/SYSTEM_ARCHITECTURE.md rule 1): the ``patients`` table is this
module's; other modules resolve patients through this service, never by querying the
table. Lookups return the profile row (or None) — they say nothing about what the caller
may *do* with the patient, which is the authorization layers' job (ADR-013).
"""

from collections.abc import Collection, Mapping
from uuid import UUID

from app.modules.patients.models import Patient
from app.modules.patients.repository import PatientRepository


class PatientDirectoryService:
    def __init__(self, patients: PatientRepository) -> None:
        self._patients = patients

    async def get_by_user_id(self, user_id: UUID) -> Patient | None:
        return await self._patients.get_by_user_id(user_id)

    async def health_ids_by_id(self, patient_ids: Collection[UUID]) -> Mapping[UUID, str]:
        """Health IDs for a set of patient rows, keyed by internal id.

        Batched by construction — a collection in, a mapping out — because the only caller
        is a listing that names many patients at once; resolving them one row at a time is
        the N+1 this method exists to prevent. Returns the *business* identifier only: no
        name, no date of birth, nothing else off the patient row. Ids that resolve to
        nothing are simply absent from the mapping.
        """
        return {
            patient.id: patient.health_id
            for patient in await self._patients.list_by_ids(patient_ids)
        }

    async def get_by_health_id(self, health_id: str) -> Patient | None:
        """Resolve a Health ID as typed at a reception desk: case-insensitive, whitespace
        tolerated (ADR-012 stores canonical uppercase)."""
        return await self._patients.get_by_health_id(health_id.strip().upper())
