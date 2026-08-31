"""records' published interfaces for other modules — identity and vocabulary, not content.

Module isolation (docs/SYSTEM_ARCHITECTURE.md rule 1): the ``doctors`` and
``record_categories`` tables are this module's. Other modules resolve clinicians and
category codes through the services here, never by querying those tables — the same
arrangement ``patients.directory`` provides for patient rows.

Both services return **records-owned projections** rather than ORM rows or another module's
types. That keeps the dependency one-directional: a consumer (today, ``consent``) depends on
records for identity, and records stays unaware of who consumes it. The only edge pointing
the other way is ``records.service`` asking consent for permission to read — a different
file, a different concern, and no import cycle between them.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.records.models import DoctorStatus
from app.modules.records.repository import DoctorRepository, RecordCategoryRepository


@dataclass(frozen=True, slots=True)
class ClinicianProfile:
    """A practitioner as other modules need them: who they are, where they practise, and
    whether they may act clinically at all (ADR-015 — a non-ACTIVE doctor fails the
    relationship layer for every clinical capability)."""

    id: UUID
    hospital_id: UUID
    is_active: bool


@dataclass(frozen=True, slots=True)
class CategoryRef:
    """A record category reduced to its two public facts: the code clients speak and the
    id foreign keys point at."""

    id: UUID
    code: str


class ClinicianDirectoryService:
    """How other modules resolve a caller to a practitioner.

    Answers who someone is, never what they may do — that is the authorization layers' job
    (ADR-013), and ``is_active`` is a fact about the profile rather than a permission.
    """

    def __init__(self, doctors: DoctorRepository) -> None:
        self._doctors = doctors

    async def get_by_user_id(self, user_id: UUID) -> ClinicianProfile | None:
        doctor = await self._doctors.get_by_user_id(user_id)
        if doctor is None:
            return None
        return ClinicianProfile(
            id=doctor.id,
            hospital_id=doctor.hospital_id,
            is_active=doctor.status is DoctorStatus.ACTIVE,
        )


class RecordCategoryDirectoryService:
    """How other modules translate between category codes and ids.

    The controlled vocabulary is ten rows (docs/DOMAIN_MODEL.md §1), so it is served whole:
    one call answers both directions for a caller that needs to resolve submitted codes and
    render stored ids in the same request.
    """

    def __init__(self, categories: RecordCategoryRepository) -> None:
        self._categories = categories

    async def list_all(self) -> list[CategoryRef]:
        return [
            CategoryRef(id=category.id, code=category.code)
            for category in await self._categories.list_all()
        ]


# -- session factories -----------------------------------------------------------------
#
# Published here rather than in ``records.dependencies`` for two reasons: a consumer should
# not have to know how this module builds its own repositories (the reach-in that
# ``records.dependencies`` still performs against ``patients`` is the pattern being avoided
# here), and keeping them in this file means a consumer imports only ``records.directory``,
# which imports nothing outside ``records`` — so no import cycle can form between a module
# that consumes identity and a module records asks for permission.


def clinician_directory(session: AsyncSession) -> ClinicianDirectoryService:
    return ClinicianDirectoryService(DoctorRepository(session))


def record_category_directory(session: AsyncSession) -> RecordCategoryDirectoryService:
    return RecordCategoryDirectoryService(RecordCategoryRepository(session))
