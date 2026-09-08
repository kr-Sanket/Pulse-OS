"""Synthea import persistence tests: idempotency, ownership, and refusal to touch data
the importer does not own.

Fixtures only — never the gitignored corpus. Object storage is the in-memory fake
(SYSTEM_ARCHITECTURE rule 4: tests never contact MinIO).
"""

import asyncio
import json
from pathlib import Path

import pytest
from app.modules.auth.domain import Role
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.patients.health_id import is_valid_health_id
from app.modules.patients.models import Patient
from app.modules.patients.repository import PatientRepository
from app.modules.records.fake import FakeObjectStorage
from app.modules.records.fhir_import import (
    SYNTHEA_DEMO_ROSTER,
    SYNTHEA_UID_PREFIX,
    ImportRefused,
    RosterEntry,
    SyntheaImporter,
    synthetic_uid,
)
from app.modules.records.fhir_mapping import FHIR_CONTENT_TYPE
from app.modules.records.models import MedicalRecord, RecordOrigin
from app.modules.records.seed import seed_reference_data
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import sqlite_session

FIXTURES = Path(__file__).parent / "fixtures" / "fhir"

#: The fixture bundle, described as a roster entry. Its identifier and name are the
#: fixture's, not the real corpus's, so these tests never depend on the dataset.
FIXTURE_ENTRY = RosterEntry(
    filename="canonical.json",
    synthea_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
    health_id="PHI-IND-2026-J0TA0DK",
    email="fixture999@synthea.pulseos.test",
    expected_name="Fixture999 Testcase999",
)


def raw(name: str = "canonical") -> bytes:
    return (FIXTURES / f"{name}.json").read_bytes()


async def _prepare(session: AsyncSession) -> FakeObjectStorage:
    """The record-category vocabulary must exist before any import — through the real seed
    function, so these tests also prove the three new codes are actually seeded."""
    await seed_reference_data(session)
    return FakeObjectStorage()


async def _records(session: AsyncSession) -> list[MedicalRecord]:
    result = await session.execute(select(MedicalRecord))
    return list(result.scalars())


# -- the happy path --------------------------------------------------------------------


def test_an_import_creates_the_patient_and_its_records() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            storage = await _prepare(session)
            outcome = await SyntheaImporter(session, storage=storage).import_bundle(
                FIXTURE_ENTRY, raw()
            )
            assert outcome.patient_created is True
            assert outcome.records_created == 7
            assert outcome.records_skipped == 0
            assert outcome.health_id == FIXTURE_ENTRY.health_id
            assert outcome.full_name == "Fixture999 Testcase999"

            patient = await PatientRepository(session).get_by_health_id(FIXTURE_ENTRY.health_id)
            assert patient is not None
            assert len(await _records(session)) == 7

    asyncio.run(scenario())


def test_every_record_is_stored_as_a_fhir_object_under_a_uuid_only_key() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            storage = await _prepare(session)
            await SyntheaImporter(session, storage=storage).import_bundle(FIXTURE_ENTRY, raw())
            records = await _records(session)
            assert len(storage.objects) == len(records)
            for record in records:
                stored = storage.objects[record.s3_key]
                assert stored.content_type == FHIR_CONTENT_TYPE
                assert record.size_bytes == len(stored.data)
                # Mirrors RecordService._store: UUIDs only, no filename (SECURITY.md).
                assert record.s3_key == f"records/{record.patient_id}/{record.id}"
                assert json.loads(stored.data)["resourceType"]

    asyncio.run(scenario())


# -- ownership and consent posture -----------------------------------------------------


def test_imported_records_are_patient_owned_with_no_hospital_provenance() -> None:
    """The load-bearing assertion of OD-S1. A non-null ``uploaded_by_hospital_id`` would
    hand that hospital ADR-013 layer-2 own-upload read access to imported records — a
    consent bypass dressed up as a data-modelling shortcut."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            storage = await _prepare(session)
            await SyntheaImporter(session, storage=storage).import_bundle(FIXTURE_ENTRY, raw())
            for record in await _records(session):
                assert record.origin is RecordOrigin.PATIENT_LOCKER
                assert record.uploaded_by_hospital_id is None
                assert record.uploaded_by_doctor_id is None
                assert record.is_hidden is False

    asyncio.run(scenario())


def test_an_import_mints_no_grant_and_no_audit_event() -> None:
    """An import is not an access. Imported records enter the consent model only through
    ``consent.enforce``, which keys on (patient, category) and never on origin."""

    async def scenario() -> None:
        from app.modules.consent.models import AuditLog, ConsentGrant, ConsentRequest

        async with sqlite_session() as session:
            storage = await _prepare(session)
            await SyntheaImporter(session, storage=storage).import_bundle(FIXTURE_ENTRY, raw())
            for table in (AuditLog, ConsentGrant, ConsentRequest):
                assert list((await session.execute(select(table))).scalars()) == []

    asyncio.run(scenario())


def test_the_imported_identity_cannot_authenticate() -> None:
    """``auth/seed.py`` refuses non-``synthetic:`` subjects, so the import cannot plant a
    login-capable identity. Signing in as one is a deliberate, separate act
    (``scripts/dev_link_identity.py``)."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            storage = await _prepare(session)
            await SyntheaImporter(session, storage=storage).import_bundle(FIXTURE_ENTRY, raw())
            user = await UserRepository(session).get_by_firebase_uid(
                synthetic_uid(FIXTURE_ENTRY.synthea_id)
            )
            assert user is not None
            assert user.firebase_uid.startswith(SYNTHEA_UID_PREFIX)
            assert user.role is Role.PATIENT
            assert user.email == FIXTURE_ENTRY.email

    asyncio.run(scenario())


# -- idempotency -----------------------------------------------------------------------


def test_importing_twice_changes_nothing() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            storage = await _prepare(session)
            importer = SyntheaImporter(session, storage=storage)
            first = await importer.import_bundle(FIXTURE_ENTRY, raw())
            before = {record.id: record.s3_key for record in await _records(session)}

            second = await importer.import_bundle(FIXTURE_ENTRY, raw())
            after = {record.id: record.s3_key for record in await _records(session)}

            assert second.patient_created is False
            assert second.records_created == 0
            assert second.records_skipped == first.records_created
            assert after == before
            assert len(storage.objects) == len(before)

    asyncio.run(scenario())


def test_a_partial_import_completes_on_the_next_run() -> None:
    """Re-running is the repair mechanism: whatever is missing is inserted, whatever is
    present is left alone."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            storage = await _prepare(session)
            importer = SyntheaImporter(session, storage=storage)
            await importer.import_bundle(FIXTURE_ENTRY, raw())
            records = await _records(session)
            victim = records[0]
            await session.delete(victim)
            await session.flush()

            outcome = await importer.import_bundle(FIXTURE_ENTRY, raw())
            assert outcome.records_created == 1
            assert outcome.records_skipped == len(records) - 1
            assert {r.id for r in await _records(session)} == {r.id for r in records}

    asyncio.run(scenario())


# -- refusals --------------------------------------------------------------------------


def test_a_bundle_that_is_not_the_rostered_one_is_refused() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            storage = await _prepare(session)
            wrong = RosterEntry(
                filename="canonical.json",
                synthea_id="not-the-fixtures-identifier",
                health_id=FIXTURE_ENTRY.health_id,
                email=FIXTURE_ENTRY.email,
                expected_name=FIXTURE_ENTRY.expected_name,
            )
            with pytest.raises(ImportRefused, match="does not match the roster"):
                await SyntheaImporter(session, storage=storage).import_bundle(wrong, raw())

    asyncio.run(scenario())


def test_a_name_that_disagrees_with_the_roster_is_refused() -> None:
    """The corpus-drift guard: a pinned Health ID must never end up on a different person."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            storage = await _prepare(session)
            renamed = RosterEntry(
                filename="canonical.json",
                synthea_id=FIXTURE_ENTRY.synthea_id,
                health_id=FIXTURE_ENTRY.health_id,
                email=FIXTURE_ENTRY.email,
                expected_name="Somebody Else",
            )
            with pytest.raises(ImportRefused, match="does not match the roster entry"):
                await SyntheaImporter(session, storage=storage).import_bundle(renamed, raw())

    asyncio.run(scenario())


def test_a_health_id_belonging_to_someone_else_is_never_adopted() -> None:
    """The protection for the three existing demo patients: the importer refuses rather
    than attaching imported records to an identity it did not create."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            storage = await _prepare(session)
            incumbent = User(firebase_uid="synthetic:patient:incumbent", role=Role.PATIENT)
            session.add(incumbent)
            await session.flush()
            session.add(
                Patient(
                    user_id=incumbent.id,
                    health_id=FIXTURE_ENTRY.health_id,
                    full_name="Existing Demo Patient",
                )
            )
            await session.flush()

            with pytest.raises(ImportRefused, match="already belongs to another patient"):
                await SyntheaImporter(session, storage=storage).import_bundle(FIXTURE_ENTRY, raw())

    asyncio.run(scenario())


def test_an_unseeded_category_is_refused_rather_than_silently_dropped() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            storage = FakeObjectStorage()  # no seed_reference_data
            with pytest.raises(ImportRefused, match="not seeded"):
                await SyntheaImporter(session, storage=storage).import_bundle(FIXTURE_ENTRY, raw())

    asyncio.run(scenario())


# -- the pinned roster -----------------------------------------------------------------


def test_the_roster_is_ten_distinct_patients_with_valid_pinned_health_ids() -> None:
    """``generate_health_id`` draws from ``secrets``, so these had to be pinned; pinning
    them is worthless if they are not real ADR-012 identifiers."""
    assert len(SYNTHEA_DEMO_ROSTER) == 10
    for entry in SYNTHEA_DEMO_ROSTER:
        assert is_valid_health_id(entry.health_id), entry.health_id
    for field in ("synthea_id", "health_id", "email", "filename"):
        values = [getattr(entry, field) for entry in SYNTHEA_DEMO_ROSTER]
        assert len(set(values)) == 10, f"{field} is not unique across the roster"


def test_the_roster_cannot_collide_with_the_existing_demo_patients() -> None:
    """The seeded demo patients (Aarav, Meera, Joseph) must be unreachable from an import."""
    from app.modules.patients.seed import SYNTHETIC_PATIENTS

    seeded_health_ids = {health_id for _, health_id, *_ in SYNTHETIC_PATIENTS}
    seeded_uids = {firebase_uid for firebase_uid, *_ in SYNTHETIC_PATIENTS}
    for entry in SYNTHEA_DEMO_ROSTER:
        assert entry.health_id not in seeded_health_ids
        assert synthetic_uid(entry.synthea_id) not in seeded_uids


def test_the_canonical_demo_patient_is_first_and_stable() -> None:
    """``--patients 1`` must always mean the same patient, so the demo script is reproducible."""
    canonical = SYNTHEA_DEMO_ROSTER[0]
    assert canonical.expected_name == "Joaquin141 Rice937"
    assert canonical.health_id == "PHI-IND-2026-J0TA0DK"
    assert canonical.email == "joaquin141.rice937@synthea.pulseos.test"
