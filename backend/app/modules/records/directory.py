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

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.records.models import Doctor, DoctorStatus, Hospital, MedicalRecord
from app.modules.records.repository import (
    DoctorRepository,
    HospitalAdminRepository,
    HospitalRepository,
    RecordCategoryRepository,
)


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


@dataclass(frozen=True, slots=True)
class StaffDisplay:
    """A member of hospital staff as a *patient* may be shown them.

    Three facts, chosen for one purpose: to let someone reading their own consent inbox or
    audit trail recognise who is on the other side. Deliberately no ids, no registration
    number, no email, no employment status — a patient decides whether to share records
    with a named clinician at a named hospital, and nothing else on the staff row helps
    with that decision (docs/SECURITY.md: expose the minimum that serves the use case).

    ``specialty`` is whatever the row already carries and is often absent; ``hospital_name``
    is never absent, because every staff row belongs to a hospital by schema.
    """

    full_name: str
    specialty: str | None
    hospital_name: str


@dataclass(frozen=True, slots=True)
class HospitalDisplay:
    """An organisation as a patient may be shown one: the identifier they already see on
    their records, and its name.

    Distinct from ``StaffDisplay.hospital_name`` and not interchangeable with it.
    ``StaffDisplay`` answers "where does this person work **now**", which is what a patient
    weighing a consent request needs. This answers "which organisation is this", and the
    caller supplies the id — so an audit trail can name the hospital an event was
    *attributed to at the time* (ADR-023) instead of the actor's present employer.
    """

    hid: str
    name: str


class StaffDirectoryService:
    """Display names for the staff a patient-facing listing refers to.

    Separate from ``ClinicianDirectoryService`` on purpose: that one answers "may this
    person act", this one answers "what do we call them", and the two must not become one
    object that leaks employment status into a patient's screen.

    **Every method takes a collection and answers a mapping.** A page of consent requests
    or audit entries names many people, and resolving them one row at a time is the N+1 this
    service exists to prevent: one statement per kind of identity, per page, whatever the
    page size. Ids that resolve to nothing are simply absent from the mapping — a caller
    renders what it got and never has to distinguish "missing" from "failed".
    """

    def __init__(
        self,
        doctors: DoctorRepository,
        admins: HospitalAdminRepository,
        hospitals: HospitalRepository,
    ) -> None:
        self._doctors = doctors
        self._admins = admins
        self._hospitals = hospitals

    async def clinicians_by_id(self, doctor_ids: Collection[UUID]) -> dict[UUID, StaffDisplay]:
        """Practitioners keyed by their own id — how consent records a requester or grantee."""
        rows = await self._doctors.list_with_hospital_by_ids(doctor_ids)
        return {doctor.id: _clinician_display(doctor, hospital) for doctor, hospital in rows}

    async def staff_by_user_id(self, user_ids: Collection[UUID]) -> dict[UUID, StaffDisplay]:
        """Staff keyed by account id — how the audit trail records who acted.

        Both kinds of staff are resolved because both appear in a patient's trail: a
        clinician reading a record, and an administrator uploading one. Accounts that are
        neither (the patient themselves, a platform administrator) resolve to nothing, which
        is the truthful answer — this module knows no name for them.
        """
        clinicians = await self._doctors.list_with_hospital_by_user_ids(user_ids)
        admins = await self._admins.list_with_hospital_by_user_ids(user_ids)
        displays = {
            doctor.user_id: _clinician_display(doctor, hospital) for doctor, hospital in clinicians
        }
        displays.update(
            {
                admin.user_id: StaffDisplay(
                    full_name=admin.full_name, specialty=None, hospital_name=hospital.name
                )
                for admin, hospital in admins
            }
        )
        return displays

    async def administered_hospital_id(self, user_id: UUID) -> UUID | None:
        """The hospital this account administers, or None if it administers none.

        The one fact the hospital audit view needs from this module: a scope, derived
        server-side from the authenticated identity so no caller can name a hospital they
        do not administer. Deliberately returns the id alone — nothing about the admin, and
        nothing about the hospital beyond which one it is.

        Not batched, unlike everything else here, because it answers a question about the
        *caller* rather than about a page of rows: there is exactly one of them per request.
        """
        admin = await self._admins.get_by_user_id(user_id)
        return admin.hospital_id if admin is not None else None

    async def hospital_names(self, hospital_ids: Collection[UUID]) -> dict[UUID, str]:
        """Hospital display names by id — an organisation is public as its name alone."""
        hospitals = await self._hospitals.list_by_ids(hospital_ids)
        return {hospital.id: hospital.name for hospital in hospitals}

    async def hospitals_by_id(self, hospital_ids: Collection[UUID]) -> dict[UUID, HospitalDisplay]:
        """Organisations keyed by id, with the identifier a patient already sees on records.

        A sibling of ``hospital_names`` rather than a replacement: that one serves a caller
        that has only ever needed a label, and widening its return type would make every
        consumer restate a field it does not use. This one exists because a *grouped* view
        needs a stable key — a name is not one, and two organisations may share it.
        """
        hospitals = await self._hospitals.list_by_ids(hospital_ids)
        return {
            hospital.id: HospitalDisplay(hid=hospital.hid, name=hospital.name)
            for hospital in hospitals
        }


def _clinician_display(doctor: Doctor, hospital: Hospital) -> StaffDisplay:
    return StaffDisplay(
        full_name=doctor.full_name, specialty=doctor.specialty, hospital_name=hospital.name
    )


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


def staff_directory(session: AsyncSession) -> StaffDirectoryService:
    return StaffDirectoryService(
        DoctorRepository(session), HospitalAdminRepository(session), HospitalRepository(session)
    )


class RecordDateDirectoryService:
    """How other modules look up clinical dates of service by record id.

    Exposes only the date_of_service projection for requested record ids.
    No content, no filename, no medical details.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def dates_by_record_ids(self, record_ids: Collection[UUID]) -> dict[UUID, date]:
        """Return a mapping of record_id to date_of_service in a single batched query."""
        if not record_ids:
            return {}
        stmt = (
            select(MedicalRecord.id, MedicalRecord.date_of_service)
            .where(MedicalRecord.id.in_(record_ids))
        )
        result = await self._session.execute(stmt)
        return {rec_id: dos for rec_id, dos in result.tuples().all() if dos is not None}


def record_date_directory(session: AsyncSession) -> RecordDateDirectoryService:
    return RecordDateDirectoryService(session)
