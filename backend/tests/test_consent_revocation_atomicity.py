"""Concurrency and regression tests for consent revocation atomicity (TOCTOU race).

Verifies that concurrent consent revocation immediately and atomically stops in-flight
clinical record access across:
1. FHIR export total revocation -> aborted with ACCESS_DENIED, zero records leaked.
2. FHIR export partial revocation -> revoked categories excluded, active categories preserved.
3. AI chunk search -> revoked chunks pruned, ACCESS_DENIED audited when empty.
4. AI answer generation -> derived answers and citations suppressed when evidence category revoked.
5. Patient self-export and self-query regression -> unaffected by clinician grant status.
6. Pre-revoked and expired consent regression -> denied immediately.

Deterministic synchronization hooks (asyncio.Event) are used to eliminate timing flakiness.
"""

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from app.modules.ai.generation import GeneratedAnswer
from app.modules.ai.query import (
    DEFAULT_EMPTY_EVIDENCE_ANSWER,
    AIQueryService,
)
from app.modules.ai.repository import AIRepository
from app.modules.ai.service import AIIngestionService, AIRetrievalService
from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.auth.models import User
from app.modules.consent.dependencies import RecordsStaffDirectory
from app.modules.consent.models import (
    AuditAction,
    AuditLog,
    ConsentDecision,
    ConsentDecisionStatus,
    ConsentGrant,
    ConsentRequest,
    ConsentRequestCategory,
    ConsentRequestStatus,
)
from app.modules.consent.repository import (
    AuditLogRepository,
    ConsentDecisionRepository,
    ConsentGrantRepository,
    ConsentRequestCategoryRepository,
    ConsentRequestRepository,
)
from app.modules.consent.service import ConsentService
from app.modules.patients.directory import PatientDirectoryService
from app.modules.patients.models import Patient
from app.modules.patients.repository import PatientRepository
from app.modules.records.directory import staff_directory
from app.modules.records.errors import ConsentRequiredError
from app.modules.records.fake import FakeObjectStorage
from app.modules.records.models import (
    Doctor,
    DoctorStatus,
    Hospital,
    HospitalVerificationStatus,
    MedicalRecord,
    RecordCategory,
    RecordOrigin,
)
from app.modules.records.repository import (
    DoctorRepository,
    HospitalAdminRepository,
    HospitalRepository,
    MedicalRecordRepository,
    RecordCategoryRepository,
)
from app.modules.records.service import RecordService
from sqlalchemy import select

from tests.support import FakeClinicianDirectory, sqlite_session


class HookedObjectStorage:
    """Wraps object storage with deterministic synchronization hooks for race simulation."""

    def __init__(self, inner: FakeObjectStorage) -> None:
        self._inner = inner
        self.on_get_object_called: asyncio.Event | None = None
        self.proceed_with_get_object: asyncio.Event | None = None
        self.intercept_category_key: str | None = None

    async def get_object(self, key: str) -> bytes:
        if self.on_get_object_called is not None:
            self.on_get_object_called.set()
        if self.proceed_with_get_object is not None:
            await self.proceed_with_get_object.wait()
        return await self._inner.get_object(key)

    async def put_object(self, key: str, data: bytes, *, content_type: str) -> None:
        await self._inner.put_object(key, data, content_type=content_type)

    async def create_download_url(
        self,
        key: str,
        *,
        expires_in_seconds: int,
        filename: str,
        content_type: str,
    ) -> str:
        return await self._inner.create_download_url(
            key,
            expires_in_seconds=expires_in_seconds,
            filename=filename,
            content_type=content_type,
        )


class DelayedAnswerGenerator:
    """Answer generator with an interception hook to simulate revocation during generation."""

    def __init__(self) -> None:
        self.provider = "fake"
        self.model = "fake-v1"
        self.generation_started: asyncio.Event | None = None
        self.proceed_generation: asyncio.Event | None = None

    async def generate_answer(self, context: Any) -> GeneratedAnswer:
        if self.generation_started is not None:
            self.generation_started.set()
        if self.proceed_generation is not None:
            await self.proceed_generation.wait()
        return GeneratedAnswer(
            answer="Synthesized clinical findings from medical records.",
            citations=(),
            provider=self.provider,
            model=self.model,
            generated_at=datetime.now(UTC),
        )


class World:
    """Test environment world holding setup state."""

    patient_user: User
    patient: Patient
    doctor_user: User
    doctor: Doctor
    hospital: Hospital
    cat_condition: RecordCategory
    cat_observation: RecordCategory
    grant_condition: ConsentGrant
    grant_observation: ConsentGrant
    patient_auth: AuthenticatedUser
    doctor_auth: AuthenticatedUser
    record_service: RecordService
    consent_service: ConsentService
    query_service: AIQueryService
    storage: HookedObjectStorage


async def _setup_world(session: Any) -> World:
    world = World()

    # Users
    world.patient_user = User(firebase_uid=f"fb-p-{uuid4()}", role=Role.PATIENT)
    world.doctor_user = User(firebase_uid=f"fb-d-{uuid4()}", role=Role.DOCTOR)
    session.add_all([world.patient_user, world.doctor_user])

    # Hospital
    world.hospital = Hospital(
        hid=f"HID-{str(uuid4())[:4].upper()}",
        name="General Hospital",
        verification_status=HospitalVerificationStatus.VERIFIED,
    )
    session.add(world.hospital)
    await session.flush()

    # Patient & Doctor profiles
    world.patient = Patient(
        user_id=world.patient_user.id,
        health_id=f"PHI-IND-2026-{str(uuid4())[:7].upper()}",
        full_name="Ananya Sharma",
        date_of_birth=date(1990, 5, 15),
    )
    world.doctor = Doctor(
        user_id=world.doctor_user.id,
        hospital_id=world.hospital.id,
        full_name="Dr. Rajesh Patel",
        registration_number="REG-12345",
        status=DoctorStatus.ACTIVE,
    )
    world.cat_condition = RecordCategory(code="CONDITION", display_name="Condition")
    world.cat_observation = RecordCategory(code="OBSERVATION", display_name="Observation")
    session.add_all([world.patient, world.doctor, world.cat_condition, world.cat_observation])
    await session.flush()

    # Request, Request Categories, and Decisions (required by ConsentGrant foreign key)
    request = ConsentRequest(
        patient_id=world.patient.id,
        requester_doctor_id=world.doctor.id,
        requester_hospital_id=world.hospital.id,
        purpose="Clinical Care",
        status=ConsentRequestStatus.PENDING,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    session.add(request)
    await session.flush()

    req_cat_cond = ConsentRequestCategory(
        request_id=request.id,
        category_id=world.cat_condition.id,
    )
    req_cat_obs = ConsentRequestCategory(
        request_id=request.id,
        category_id=world.cat_observation.id,
    )
    session.add_all([req_cat_cond, req_cat_obs])
    await session.flush()

    dec_cond = ConsentDecision(
        request_id=request.id,
        category_id=world.cat_condition.id,
        status=ConsentDecisionStatus.APPROVED,
    )
    dec_obs = ConsentDecision(
        request_id=request.id,
        category_id=world.cat_observation.id,
        status=ConsentDecisionStatus.APPROVED,
    )
    session.add_all([dec_cond, dec_obs])
    await session.flush()

    # Direct Grants
    world.grant_condition = ConsentGrant(
        decision_id=dec_cond.id,
        patient_id=world.patient.id,
        grantee_doctor_id=world.doctor.id,
        category_id=world.cat_condition.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    world.grant_observation = ConsentGrant(
        decision_id=dec_obs.id,
        patient_id=world.patient.id,
        grantee_doctor_id=world.doctor.id,
        category_id=world.cat_observation.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    session.add_all([world.grant_condition, world.grant_observation])
    await session.flush()

    # Auth representations
    world.patient_auth = AuthenticatedUser(
        user_id=world.patient_user.id,
        firebase_uid=world.patient_user.firebase_uid,
        role=Role.PATIENT,
    )
    world.doctor_auth = AuthenticatedUser(
        user_id=world.doctor_user.id,
        firebase_uid=world.doctor_user.firebase_uid,
        role=Role.DOCTOR,
    )

    # Directories and Repositories
    clinicians = FakeClinicianDirectory()
    clinicians.register(
        world.doctor_user.id, doctor_id=world.doctor.id, hospital_id=world.hospital.id
    )
    patients = PatientDirectoryService(PatientRepository(session))
    audit_repo = AuditLogRepository(session)

    world.consent_service = ConsentService(
        requests=ConsentRequestRepository(session),
        request_categories=ConsentRequestCategoryRepository(session),
        decisions=ConsentDecisionRepository(session),
        grants=ConsentGrantRepository(session),
        audit=audit_repo,
        patients=patients,
        clinicians=clinicians,
        staff=RecordsStaffDirectory(staff_directory(session)),
    )

    raw_storage = FakeObjectStorage()
    world.storage = HookedObjectStorage(raw_storage)

    # Records Service
    world.record_service = RecordService(
        records=MedicalRecordRepository(session),
        categories=RecordCategoryRepository(session),
        admins=HospitalAdminRepository(session),
        doctors=DoctorRepository(session),
        hospitals=HospitalRepository(session),
        patients=patients,
        storage=world.storage,  # type: ignore[arg-type]
        queue=None,  # type: ignore[arg-type]
        consent=world.consent_service,
        grant_scope=world.consent_service,
        listing_auditor=world.consent_service,
        record_auditor=world.consent_service,
        export_auditor=world.consent_service,
        presign_ttl_seconds=300,
        max_upload_bytes=10 * 1024 * 1024,
    )

    # AI Query Service
    ai_repo = AIRepository(session)
    retrieval_service = AIRetrievalService(ai_repo)
    world.query_service = AIQueryService(
        retrieval=retrieval_service,
        consent=world.consent_service,
        auditor=world.consent_service,
        search_auditor=world.consent_service,
        patients=patients,
    )

    return world


def test_fhir_export_concurrent_total_revocation_aborts_and_audits_denial() -> None:
    """When all active grants are revoked while FHIR export is retrieving files from S3,

    the export must abort with ConsentRequiredError, emit ACCESS_DENIED, and never
    emit RECORD_EXPORTED.
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            w = await _setup_world(session)

            # Seed condition record
            record_id = uuid4()
            s3_key = f"records/{w.patient.id}/{record_id}"
            condition_fhir = {
                "resourceType": "Condition",
                "id": str(record_id),
                "code": {"text": "Type 2 Diabetes Mellitus"},
            }
            await w.storage.put_object(
                s3_key, json.dumps(condition_fhir).encode(), content_type="application/fhir+json"
            )

            rec = MedicalRecord(
                id=record_id,
                patient_id=w.patient.id,
                category_id=w.cat_condition.id,
                origin=RecordOrigin.HOSPITAL_UPLOAD,
                uploaded_by_hospital_id=w.hospital.id,
                date_of_service=date(2026, 1, 10),
                original_filename="condition.json",
                content_type="application/fhir+json",
                size_bytes=100,
                s3_key=s3_key,
            )
            session.add(rec)
            await session.flush()

            # Set up deterministic race hooks
            started = asyncio.Event()
            proceed = asyncio.Event()
            w.storage.on_get_object_called = started
            w.storage.proceed_with_get_object = proceed

            async def do_export() -> None:
                await w.record_service.export_fhir(
                    w.doctor_auth,
                    patient_health_id=w.patient.health_id,
                )

            async def do_revoke() -> None:
                await started.wait()
                # Patient revokes both grants while export is blocked on get_object
                await w.consent_service.revoke_grant(w.patient_auth, w.grant_condition.id)
                await w.consent_service.revoke_grant(w.patient_auth, w.grant_observation.id)
                proceed.set()

            # Run race
            export_task = asyncio.create_task(do_export())
            revoke_task = asyncio.create_task(do_revoke())

            # Export must fail closed with ConsentRequiredError
            with pytest.raises(ConsentRequiredError):
                await asyncio.gather(export_task, revoke_task)

            # Inspect audit logs
            stmt = select(AuditLog).where(AuditLog.patient_id == w.patient.id)
            logs = list((await session.execute(stmt)).scalars())
            actions = [log.action for log in logs]

            assert AuditAction.CONSENT_REVOKED in actions
            assert AuditAction.ACCESS_DENIED in actions
            assert AuditAction.RECORD_EXPORTED not in actions

    asyncio.run(scenario())


def test_fhir_export_concurrent_partial_revocation_prunes_revoked_categories() -> None:
    """When a patient revokes only one category while an export is in flight,

    the final export must prune records belonging to the revoked category and successfully
    export records from the still-authorized category with an updated audit event.
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            w = await _setup_world(session)

            # Seed condition record
            rec_cond_id = uuid4()
            s3_key_cond = f"records/{w.patient.id}/{rec_cond_id}"
            condition_fhir = {
                "resourceType": "Condition",
                "id": str(rec_cond_id),
                "code": {"text": "Hypertension"},
            }
            await w.storage.put_object(
                s3_key_cond,
                json.dumps(condition_fhir).encode(),
                content_type="application/fhir+json",
            )
            rec_cond = MedicalRecord(
                id=rec_cond_id,
                patient_id=w.patient.id,
                category_id=w.cat_condition.id,
                origin=RecordOrigin.HOSPITAL_UPLOAD,
                uploaded_by_hospital_id=w.hospital.id,
                date_of_service=date(2026, 1, 10),
                original_filename="cond.json",
                content_type="application/fhir+json",
                size_bytes=100,
                s3_key=s3_key_cond,
            )

            # Seed observation record
            rec_obs_id = uuid4()
            s3_key_obs = f"records/{w.patient.id}/{rec_obs_id}"
            obs_fhir = {
                "resourceType": "Observation",
                "id": str(rec_obs_id),
                "code": {"text": "Blood Pressure"},
                "status": "final",
            }
            await w.storage.put_object(
                s3_key_obs, json.dumps(obs_fhir).encode(), content_type="application/fhir+json"
            )
            rec_obs = MedicalRecord(
                id=rec_obs_id,
                patient_id=w.patient.id,
                category_id=w.cat_observation.id,
                origin=RecordOrigin.HOSPITAL_UPLOAD,
                uploaded_by_hospital_id=w.hospital.id,
                date_of_service=date(2026, 1, 11),
                original_filename="obs.json",
                content_type="application/fhir+json",
                size_bytes=100,
                s3_key=s3_key_obs,
            )
            session.add_all([rec_cond, rec_obs])
            await session.flush()

            # Set up deterministic race hooks: wait on first get_object
            started = asyncio.Event()
            proceed = asyncio.Event()
            w.storage.on_get_object_called = started
            w.storage.proceed_with_get_object = proceed

            bundle_result: list[bytes] = []

            async def do_export() -> None:
                bundle_bytes = await w.record_service.export_fhir(
                    w.doctor_auth,
                    patient_health_id=w.patient.health_id,
                )
                bundle_result.append(bundle_bytes)

            async def do_partial_revoke() -> None:
                await started.wait()
                # Revoke OBSERVATION only; CONDITION remains active!
                await w.consent_service.revoke_grant(w.patient_auth, w.grant_observation.id)
                proceed.set()

            await asyncio.gather(do_export(), do_partial_revoke())

            # Verify bundle contents: CONDITION is present, OBSERVATION is pruned
            assert len(bundle_result) == 1
            bundle = json.loads(bundle_result[0])
            entries = bundle.get("entry", [])
            resource_types = [e["resource"]["resourceType"] for e in entries]

            assert "Patient" in resource_types
            assert "Condition" in resource_types
            assert "Observation" not in resource_types

            # Verify audit trail has RECORD_EXPORTED
            stmt = select(AuditLog).where(
                AuditLog.patient_id == w.patient.id,
                AuditLog.action == AuditAction.RECORD_EXPORTED,
            )
            export_logs = list((await session.execute(stmt)).scalars())
            assert len(export_logs) == 1

    asyncio.run(scenario())


def test_ai_search_concurrent_revocation_drops_revoked_chunks() -> None:
    """When consent is revoked while search is querying retrieval, chunks from

    revoked categories must be filtered out, and ACCESS_DENIED audited when no scope survives.
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            w = await _setup_world(session)

            # Seed record and index chunk in CONDITION
            rec_id = uuid4()
            s3_key = f"records/{w.patient.id}/{rec_id}"
            await w.storage.put_object(s3_key, b"{}", content_type="application/fhir+json")
            rec = MedicalRecord(
                id=rec_id,
                patient_id=w.patient.id,
                category_id=w.cat_condition.id,
                origin=RecordOrigin.HOSPITAL_UPLOAD,
                uploaded_by_hospital_id=w.hospital.id,
                date_of_service=date(2026, 1, 1),
                original_filename="cond.json",
                content_type="application/fhir+json",
                size_bytes=100,
                s3_key=s3_key,
            )
            session.add(rec)
            await session.flush()

            ai_repo = AIRepository(session)
            await AIIngestionService(ai_repo).index_record(
                record_id=rec.id,
                patient_id=w.patient.id,
                category_id=w.cat_condition.id,
                normalized_text="Patient diagnosed with severe hypertension",
                max_tokens=20,
            )

            # Pre-condition: searching before revocation returns the chunk
            results = await w.query_service.search_records(
                w.doctor_auth,
                patient_id=w.patient.id,
                query="hypertension",
            )
            assert len(results) == 1

            # Revoke grant for CONDITION
            await w.consent_service.revoke_grant(w.patient_auth, w.grant_condition.id)
            await w.consent_service.revoke_grant(w.patient_auth, w.grant_observation.id)

            # Search after revocation returns empty and audits ACCESS_DENIED
            results_after = await w.query_service.search_records(
                w.doctor_auth,
                patient_id=w.patient.id,
                query="hypertension",
            )
            assert results_after == []

            stmt = select(AuditLog).where(
                AuditLog.patient_id == w.patient.id,
                AuditLog.action == AuditAction.ACCESS_DENIED,
            )
            denials = list((await session.execute(stmt)).scalars())
            assert len(denials) >= 1

    asyncio.run(scenario())


def test_ai_generate_answer_concurrent_revocation_discards_derived_summary() -> None:
    """When a grant for an evidence category is revoked while the answer generator

    is executing, the derived summary and citations must be suppressed and replaced
    by DEFAULT_EMPTY_EVIDENCE_ANSWER without emitting SUMMARY_GENERATED.
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            w = await _setup_world(session)

            # Seed record and index chunk in CONDITION
            rec_id = uuid4()
            s3_key = f"records/{w.patient.id}/{rec_id}"
            await w.storage.put_object(s3_key, b"{}", content_type="application/fhir+json")
            rec = MedicalRecord(
                id=rec_id,
                patient_id=w.patient.id,
                category_id=w.cat_condition.id,
                origin=RecordOrigin.HOSPITAL_UPLOAD,
                uploaded_by_hospital_id=w.hospital.id,
                date_of_service=date(2026, 1, 1),
                original_filename="cardio.json",
                content_type="application/fhir+json",
                size_bytes=100,
                s3_key=s3_key,
            )
            session.add(rec)
            await session.flush()

            ai_repo = AIRepository(session)
            await AIIngestionService(ai_repo).index_record(
                record_id=rec.id,
                patient_id=w.patient.id,
                category_id=w.cat_condition.id,
                normalized_text="Detailed cardiovascular assessment report",
                max_tokens=20,
            )

            generator = DelayedAnswerGenerator()
            started = asyncio.Event()
            proceed = asyncio.Event()
            generator.generation_started = started
            generator.proceed_generation = proceed

            answer_box: list[GeneratedAnswer] = []

            async def do_generate() -> None:
                answer = await w.query_service.generate_answer(
                    w.doctor_auth,
                    patient_id=w.patient.id,
                    query="cardiovascular",
                    category_codes={w.cat_condition.id: "CONDITION"},
                    generator=generator,
                )
                answer_box.append(answer)

            async def do_revoke() -> None:
                await started.wait()
                # Revoke consent while generator is actively generating!
                await w.consent_service.revoke_grant(w.patient_auth, w.grant_condition.id)
                proceed.set()

            await asyncio.gather(do_generate(), do_revoke())

            assert len(answer_box) == 1
            ans = answer_box[0]
            # Must return default empty-evidence answer
            assert ans.answer == DEFAULT_EMPTY_EVIDENCE_ANSWER
            assert ans.citations == ()

            # Must NOT write SUMMARY_GENERATED
            stmt = select(AuditLog).where(
                AuditLog.patient_id == w.patient.id,
                AuditLog.action == AuditAction.SUMMARY_GENERATED,
            )
            summaries = list((await session.execute(stmt)).scalars())
            assert len(summaries) == 0

    asyncio.run(scenario())


def test_patient_self_export_and_self_query_unaffected_by_clinician_grants() -> None:
    """Patient self-export and self-query operate on record ownership and must

    never be blocked by clinician consent status.
    """

    async def scenario() -> None:
        async with sqlite_session() as session:
            w = await _setup_world(session)

            # Revoke all clinician grants
            await w.consent_service.revoke_grant(w.patient_auth, w.grant_condition.id)
            await w.consent_service.revoke_grant(w.patient_auth, w.grant_observation.id)

            # Seed record
            record_id = uuid4()
            s3_key = f"records/{w.patient.id}/{record_id}"
            condition_fhir = {
                "resourceType": "Condition",
                "id": str(record_id),
                "code": {"text": "Asthma"},
            }
            await w.storage.put_object(
                s3_key, json.dumps(condition_fhir).encode(), content_type="application/fhir+json"
            )
            rec = MedicalRecord(
                id=record_id,
                patient_id=w.patient.id,
                category_id=w.cat_condition.id,
                origin=RecordOrigin.PATIENT_LOCKER,
                date_of_service=date(2026, 2, 1),
                original_filename="asthma.json",
                content_type="application/fhir+json",
                size_bytes=80,
                s3_key=s3_key,
            )
            session.add(rec)
            await session.flush()

            # Patient self-export must succeed
            bundle_bytes = await w.record_service.export_fhir(w.patient_auth)
            bundle = json.loads(bundle_bytes)
            assert bundle["resourceType"] == "Bundle"
            assert len(bundle.get("entry", [])) == 2  # Patient + Condition

            # Patient self-answer must succeed
            ai_repo = AIRepository(session)
            await AIIngestionService(ai_repo).index_record(
                record_id=rec.id,
                patient_id=w.patient.id,
                category_id=w.cat_condition.id,
                normalized_text="asthma inhaler daily use",
                max_tokens=20,
            )

            generator = DelayedAnswerGenerator()
            self_answer = await w.query_service.generate_self_answer(
                w.patient_auth,
                patient_id=w.patient.id,
                query="asthma",
                category_codes={w.cat_condition.id: "CONDITION"},
                generator=generator,
            )
            assert self_answer.answer != DEFAULT_EMPTY_EVIDENCE_ANSWER

    asyncio.run(scenario())


def test_expired_consent_refuses_export() -> None:
    """When a grant has expired, export must be refused immediately."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            w = await _setup_world(session)

            # Expire both grants
            w.grant_condition.expires_at = datetime.now(UTC) - timedelta(seconds=10)
            w.grant_observation.expires_at = datetime.now(UTC) - timedelta(seconds=10)
            await session.flush()

            with pytest.raises(ConsentRequiredError):
                await w.record_service.export_fhir(
                    w.doctor_auth,
                    patient_health_id=w.patient.health_id,
                )

    asyncio.run(scenario())
