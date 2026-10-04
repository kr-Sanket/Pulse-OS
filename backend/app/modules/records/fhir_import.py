"""Synthea bundle → PulseOS rows. The persistence half of the import; mapping is pure
(``fhir_mapping.py``) and stays that way.

Three properties this module exists to guarantee:

**Idempotent.** Two keys, both derived and both backed by a UNIQUE constraint rather than by
bookkeeping: the patient by ``users.firebase_uid`` (``synthetic:patient:synthea:{id}``) and
each record by a UUIDv5 that produces the same ``s3_key`` on every run. Re-running finds
what exists and inserts nothing.

**Non-destructive.** It never updates a patient, a record or an object — insert-if-absent
only, exactly like ``patients/seed.py``. The three existing demo patients (Aarav, Meera,
Joseph) cannot be touched: their Health IDs are not in the roster, their ``firebase_uid``
values are not derivable from any Synthea id, and :meth:`_resolve_patient` refuses a pinned
Health ID that already belongs to a different identity rather than adopting it.

**Consent-neutral.** It writes ``medical_records`` rows and objects, and nothing else. No
grant, no access request, no audit event — an import is not an access. Imported records
enter the consent model exactly as uploaded ones do, because ``consent.enforce`` keys on
``(patient_id, category_id)`` and never looks at ``origin``: a clinician with no grant sees
nothing, and one with a grant sees only the categories they were granted.

``origin`` is ``PATIENT_LOCKER`` and both ``uploaded_by_*`` columns stay NULL (OD-S1). That
is the semantically closest existing value — patient-owned history with no hospital
provenance — and it keeps the import invisible to the UI, which renders a null hospital as
"Added by the patient". Crucially it also means no hospital gains ADR-013 layer-2
own-upload read access to imported records: attributing them to a hospital would have been
a consent bypass dressed up as a data-modelling shortcut.
"""

from dataclasses import dataclass, field
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.ingestion import AIRecordIngestion
from app.modules.auth.domain import Role
from app.modules.auth.repository import UserRepository
from app.modules.auth.seed import get_or_create_synthetic_user
from app.modules.patients.models import Patient
from app.modules.patients.repository import PatientRepository
from app.modules.records.fhir_mapping import (
    FHIR_CONTENT_TYPE,
    MappedBundle,
    map_bundle,
    parse_bundle,
)
from app.modules.records.models import MedicalRecord, RecordOrigin
from app.modules.records.repository import (
    MedicalRecordRepository,
    RecordCategoryRepository,
)
from app.modules.records.storage import ObjectStorage

#: Provider-subject prefix for imported patients. Extends the ``synthetic:`` convention
#: ``auth/seed.py`` already enforces, so an imported patient can never authenticate — the
#: demo links a real Firebase UID onto one deliberately, via
#: ``scripts/dev_link_identity.py``. This is also the only place the import is
#: operationally distinguishable, and no response model reads this column.
SYNTHEA_UID_PREFIX: Final = "synthetic:patient:synthea:"


def synthetic_uid(synthea_id: str) -> str:
    return f"{SYNTHEA_UID_PREFIX}{synthea_id}"


class ImportRefused(Exception):
    """The bundle does not match its roster entry, or importing it would touch an identity
    the importer does not own. Never partially applied — the caller rolls the bundle back."""


@dataclass(frozen=True, slots=True)
class RosterEntry:
    """One pinned demo patient.

    The Health ID is pinned rather than generated because ``generate_health_id`` draws from
    ``secrets`` — a fresh draw on every run would mint a second identity for the same
    Synthea patient and break idempotency at the one place it matters most. Each was drawn
    once with the real generator, verified by ``is_valid_health_id``, and checked against
    the three existing demo patients for collisions.

    ``expected_name`` is an integrity check, not data: the name PulseOS stores comes from
    the bundle. If the two disagree, the corpus is not the one this roster was pinned
    against and the import refuses rather than importing a stranger under a pinned Health ID.
    """

    filename: str
    synthea_id: str
    health_id: str
    email: str
    expected_name: str


#: The Review-1 demo roster (OD-S3: ten patients). Selection was deterministic, not random:
#: alive, all eight clinical resource types present, 0.4 to 2.5 MB (excluding the 40 MB
#: outlier), no distressing presentation topics, then ranked by condition/medication/
#: procedure counts with the filename as a stable tie-break.
#:
#: The first entry is the canonical demo patient. Its value is narrative rather than volume:
#: obesity (1987) → prediabetes → diabetes (1993) → metabolic syndrome → diabetic
#: retinopathy (1999) → macular edema (2015), on Metformin and Simvastatin, evidenced by 21
#: lipid panels, 11 basic and 10 comprehensive metabolic panels and a haemogram. It reads to
#: a reviewer as a real thirty-year patient history, and it lands on categories the seeded
#: vocabulary already had.
SYNTHEA_DEMO_ROSTER: Final[tuple[RosterEntry, ...]] = (
    RosterEntry(
        "Joaquin141_Rice937_75b72703-7516-472e-b73f-c539638a5955.json",
        "75b72703-7516-472e-b73f-c539638a5955",
        "PHI-IND-2026-J0TA0DK",
        "joaquin141.rice937@synthea.pulseos.test",
        "Joaquin141 Rice937",
    ),  # canonical — 103 records: 16 conditions, 43 labs, 20 medications, 8 procedures
    RosterEntry(
        "Karena692_Dietrich576_da6eed88-4547-4ef0-9307-16e1fd770027.json",
        "da6eed88-4547-4ef0-9307-16e1fd770027",
        "PHI-IND-2026-YH0NRM8",
        "karena692.dietrich576@synthea.pulseos.test",
        "Karena692 Dietrich576",
    ),
    RosterEntry(
        "Hobert364_Lynch190_fb68b191-6b88-49ff-b589-5b5a57050700.json",
        "fb68b191-6b88-49ff-b589-5b5a57050700",
        "PHI-IND-2026-C11JFF8",
        "hobert364.lynch190@synthea.pulseos.test",
        "Hobert364 Lynch190",
    ),
    RosterEntry(
        "Louis204_Wiza601_41e2c1c5-477f-46d4-ad64-3adcbe1f6aaa.json",
        "41e2c1c5-477f-46d4-ad64-3adcbe1f6aaa",
        "PHI-IND-2026-TV3PVKQ",
        "louis204.wiza601@synthea.pulseos.test",
        "Louis204 Wiza601",
    ),
    RosterEntry(
        "Darwin703_Upton904_e93936a8-64bc-41b0-8d89-ad227d9565d9.json",
        "e93936a8-64bc-41b0-8d89-ad227d9565d9",
        "PHI-IND-2026-YVT9M52",
        "darwin703.upton904@synthea.pulseos.test",
        "Darwin703 Upton904",
    ),
    RosterEntry(
        "Verline727_MacGyver246_8e47055c-9c3d-444b-8b85-ae7a800f56e2.json",
        "8e47055c-9c3d-444b-8b85-ae7a800f56e2",
        "PHI-IND-2026-Z1DKJQ0",
        "verline727.macgyver246@synthea.pulseos.test",
        "Verline727 MacGyver246",
    ),
    RosterEntry(
        "Ward668_Conn188_578fa8dc-090e-42f5-955d-8ee49032ef41.json",
        "578fa8dc-090e-42f5-955d-8ee49032ef41",
        "PHI-IND-2026-GGH1QTD",
        "ward668.conn188@synthea.pulseos.test",
        "Ward668 Conn188",
    ),
    RosterEntry(
        "Ernestina649_Donnelly343_a1e2a560-efee-4735-8d42-d7132e55d1fe.json",
        "a1e2a560-efee-4735-8d42-d7132e55d1fe",
        "PHI-IND-2026-7RGH2HN",
        "ernestina649.donnelly343@synthea.pulseos.test",
        "Ernestina649 Donnelly343",
    ),
    RosterEntry(
        "Gaynell126_Abshire638_243d664f-91db-4a01-b154-c23445218635.json",
        "243d664f-91db-4a01-b154-c23445218635",
        "PHI-IND-2026-6Z150MH",
        "gaynell126.abshire638@synthea.pulseos.test",
        "Gaynell126 Abshire638",
    ),
    RosterEntry(
        "Ricky354_Zieme486_6578a971-f801-48ce-a5d1-e5af398f8f3b.json",
        "6578a971-f801-48ce-a5d1-e5af398f8f3b",
        "PHI-IND-2026-MJG4J66",
        "ricky354.zieme486@synthea.pulseos.test",
        "Ricky354 Zieme486",
    ),
)


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    health_id: str
    full_name: str
    patient_created: bool
    records_created: int
    records_skipped: int
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_records(self) -> int:
        return self.records_created + self.records_skipped


class SyntheaImporter:
    """Imports one bundle per call, into the caller's transaction.

    The caller owns the transaction boundary and must give each bundle its own, so a bundle
    that fails leaves nothing behind while its neighbours still import (skip-and-report
    across files, fail-fast within one).
    """

    def __init__(self,session: AsyncSession,*,storage: ObjectStorage,ai_ingestion: AIRecordIngestion | None = None,) -> None:
        self._session = session
        self._storage = storage
        self._ai_ingestion = ai_ingestion
        self._users = UserRepository(session)
        self._patients = PatientRepository(session)
        self._categories = RecordCategoryRepository(session)
        self._records = MedicalRecordRepository(session)

    async def import_bundle(self, entry: RosterEntry, raw: bytes) -> ImportOutcome:
        mapping = map_bundle(parse_bundle(raw))
        self._verify_against_roster(entry, mapping)
        patient, created = await self._resolve_patient(entry, mapping)

        record_created = 0
        record_skipped = 0
        for mapped in mapping.records:
            category = await self._categories.get_by_code(mapped.category_code)
            if category is None:
                raise ImportRefused(
                    f"record category {mapped.category_code!r} is not seeded; "
                    "run scripts/seed.py first"
                )
            if await self._records.get_with_context(mapped.record_id) is not None:
                record_skipped += 1
                continue
            # Mirrors RecordService._store's key shape exactly — UUIDs only, no filename
            # (docs/SECURITY.md: object keys leak). Deterministic here, so the UNIQUE
            # constraint on s3_key is the backstop under this method's existence check.
            s3_key = f"records/{patient.id}/{mapped.record_id}"
            await self._records.add(
                MedicalRecord(
                    id=mapped.record_id,
                    patient_id=patient.id,
                    category_id=category.id,
                    origin=RecordOrigin.PATIENT_LOCKER,
                    uploaded_by_hospital_id=None,
                    uploaded_by_doctor_id=None,
                    date_of_service=mapped.date_of_service,
                    description=mapped.description,
                    original_filename=mapped.title,
                    content_type=FHIR_CONTENT_TYPE,
                    size_bytes=len(mapped.resource_json),
                    s3_key=s3_key,
                )
            )
            await self._storage.put_object(
                s3_key,
                mapped.resource_json,
                content_type=FHIR_CONTENT_TYPE,
            )

            if self._ai_ingestion is not None:
                await self._ai_ingestion.index_fhir_resource(
                    record_id=mapped.record_id,
                    patient_id=patient.id,
                    category_id=category.id,
                    resource=mapped.resource_json,
                )

            record_created += 1

        return ImportOutcome(
            health_id=patient.health_id,
            full_name=patient.full_name,
            patient_created=created,
            records_created=record_created,
            records_skipped=record_skipped,
            warnings=mapping.warnings,
        )

    def _verify_against_roster(self, entry: RosterEntry, mapping: MappedBundle) -> None:
        """The bundle must be the one the roster pinned. Both checks guard the same thing —
        a pinned Health ID must not end up on a different person."""
        if mapping.patient.synthea_id != entry.synthea_id:
            raise ImportRefused(
                f"bundle identifier {mapping.patient.synthea_id} does not match the roster"
            )
        if mapping.patient.full_name != entry.expected_name:
            raise ImportRefused(
                "bundle patient name does not match the roster entry; the corpus is not the "
                "one this roster was pinned against"
            )

    async def _resolve_patient(
        self, entry: RosterEntry, mapping: MappedBundle
    ) -> tuple[Patient, bool]:
        """Find or create the imported patient, refusing to adopt an identity it does not own.

        ``get_or_create_synthetic_user`` enforces the ``synthetic:`` prefix, so this path
        cannot plant a login-capable identity even by accident.
        """
        user, _ = await get_or_create_synthetic_user(
            self._session,
            firebase_uid=synthetic_uid(entry.synthea_id),
            role=Role.PATIENT,
            email=entry.email,
        )
        existing = await self._patients.get_by_user_id(user.id)
        if existing is not None:
            return existing, False

        # The pinned Health ID must be free, or belong to nobody. A collision means either
        # the roster clashes with real seed data or a previous run half-completed; adopting
        # the row would silently attach a stranger's records to it.
        clash = await self._patients.get_by_health_id(entry.health_id)
        if clash is not None:
            raise ImportRefused(
                f"Health ID {entry.health_id} already belongs to another patient; refusing "
                "to attach imported records to it"
            )
        patient = await self._patients.add(
            Patient(
                user_id=user.id,
                health_id=entry.health_id,
                full_name=mapping.patient.full_name,
                date_of_birth=mapping.patient.date_of_birth,
                gender=mapping.patient.gender,
            )
        )
        return patient, True
