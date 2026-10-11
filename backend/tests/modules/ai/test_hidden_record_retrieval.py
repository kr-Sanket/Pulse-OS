"""Patient-hidden records must not reach doctor-facing AI retrieval (docs/DOMAIN_MODEL.md §3).

Real ConsentService, real AIRepository and AIRetrievalService, in-memory SQLite. Hiding is
applied the way ``RecordService.set_visibility`` applies it — one attribute on the persisted
``MedicalRecord`` — and never by touching the AI tables, so every test here also proves the
filter is read live rather than copied at indexing time.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

from app.modules.ai.generation import FakeAnswerGenerator
from app.modules.ai.models import AIChunk, AIDocument
from app.modules.ai.query import DEFAULT_EMPTY_EVIDENCE_ANSWER, AIQueryService
from app.modules.ai.repository import AIRepository
from app.modules.ai.service import AIIngestionService, AIRetrievalService
from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.auth.models import User
from app.modules.consent.dependencies import RecordsStaffDirectory
from app.modules.consent.models import AuditAction, AuditLog
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
from app.modules.records.models import (
    Doctor,
    DoctorStatus,
    Hospital,
    HospitalVerificationStatus,
    MedicalRecord,
    RecordCategory,
    RecordOrigin,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.support import FakeClinicianDirectory, sqlite_session


@dataclass
class World:
    session: AsyncSession
    ai_repository: AIRepository
    query_service: AIQueryService
    doctor: AuthenticatedUser
    patient: AuthenticatedUser
    patient_id: UUID
    category_codes: dict[UUID, str]
    cat_lab: UUID
    cat_rx: UUID
    # LAB_REPORT (granted when ``grant_lab``): one to hide, one that stays visible.
    lab_hidden: MedicalRecord
    lab_visible: MedicalRecord
    # PRESCRIPTION: never granted to the doctor.
    rx: MedicalRecord


async def _build_world(session: AsyncSession, *, grant_lab: bool) -> World:
    patient_user = User(firebase_uid=f"fb-patient-{uuid4()}", role=Role.PATIENT)
    doctor_user = User(firebase_uid=f"fb-doctor-{uuid4()}", role=Role.DOCTOR)
    session.add_all([patient_user, doctor_user])
    await session.flush()

    patient = Patient(
        user_id=patient_user.id,
        health_id=f"PHI-IND-2026-{str(uuid4())[:7].upper()}",
        full_name="Hidden Record Test Patient",
    )
    hospital = Hospital(
        hid=f"HID-{str(uuid4())[:4].upper()}",
        name="Test General Hospital",
        verification_status=HospitalVerificationStatus.VERIFIED,
    )
    session.add_all([patient, hospital])
    await session.flush()

    doctor = Doctor(
        user_id=doctor_user.id,
        hospital_id=hospital.id,
        full_name="Dr Clinician",
        registration_number=f"REG-{str(uuid4())[:6].upper()}",
        status=DoctorStatus.ACTIVE,
    )
    cat_lab = RecordCategory(code="LAB_REPORT", display_name="Lab Report")
    cat_rx = RecordCategory(code="PRESCRIPTION", display_name="Prescription")
    session.add_all([doctor, cat_lab, cat_rx])
    await session.flush()

    clinicians = FakeClinicianDirectory()
    clinicians.register(
        doctor_user.id, doctor_id=doctor.id, hospital_id=hospital.id, is_active=True
    )

    def record(category_id: UUID, day: int, name: str) -> MedicalRecord:
        return MedicalRecord(
            id=uuid4(),
            patient_id=patient.id,
            category_id=category_id,
            origin=RecordOrigin.HOSPITAL_UPLOAD,
            uploaded_by_hospital_id=hospital.id,
            uploaded_by_doctor_id=doctor.id,
            date_of_service=date(2026, 3, day),
            description=f"{name} description",
            original_filename=f"{name}.json",
            content_type="application/fhir+json",
            size_bytes=100,
            s3_key=f"records/{patient.id}/{name}",
        )

    lab_hidden = record(cat_lab.id, 2, "lab-hidden")
    lab_visible = record(cat_lab.id, 1, "lab-visible")
    rx = record(cat_rx.id, 3, "rx")
    session.add_all([lab_hidden, lab_visible, rx])
    await session.flush()

    ai_repository = AIRepository(session)
    ingestion = AIIngestionService(ai_repository)
    for rec, text in (
        (lab_hidden, "glucose diabetes fasting panel elevated"),
        (lab_visible, "glucose diabetes hba1c report"),
        (rx, "metformin diabetes glucose medication"),
    ):
        assert (
            await ingestion.index_record(
                record_id=rec.id,
                patient_id=patient.id,
                category_id=rec.category_id,
                normalized_text=text,
                max_tokens=20,
            )
            is not None
        )

    consent = ConsentService(
        requests=ConsentRequestRepository(session),
        request_categories=ConsentRequestCategoryRepository(session),
        decisions=ConsentDecisionRepository(session),
        grants=ConsentGrantRepository(session),
        audit=AuditLogRepository(session),
        patients=PatientDirectoryService(PatientRepository(session)),
        clinicians=clinicians,
        staff=RecordsStaffDirectory(staff_directory(session)),
    )
    doctor_auth = AuthenticatedUser(
        user_id=doctor_user.id, firebase_uid=doctor_user.firebase_uid, role=Role.DOCTOR
    )
    patient_auth = AuthenticatedUser(
        user_id=patient_user.id, firebase_uid=patient_user.firebase_uid, role=Role.PATIENT
    )

    if grant_lab:
        request_view = await consent.create_request(
            doctor_auth,
            patient_health_id=patient.health_id,
            category_ids=[cat_lab.id],
            purpose="diagnostic consultation",
        )
        await consent.approve_categories(patient_auth, request_view.request.id, [cat_lab.id])

    return World(
        session=session,
        ai_repository=ai_repository,
        query_service=AIQueryService(retrieval=AIRetrievalService(ai_repository), consent=consent),
        doctor=doctor_auth,
        patient=patient_auth,
        patient_id=patient.id,
        category_codes={cat_lab.id: "LAB_REPORT", cat_rx.id: "PRESCRIPTION"},
        cat_lab=cat_lab.id,
        cat_rx=cat_rx.id,
        lab_hidden=lab_hidden,
        lab_visible=lab_visible,
        rx=rx,
    )


async def _set_hidden(world: World, record: MedicalRecord, hidden: bool) -> None:
    record.is_hidden = hidden
    await world.session.flush()


async def _summary_audit_count(world: World) -> int:
    result = await world.session.execute(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == AuditAction.SUMMARY_GENERATED)
    )
    return int(result.scalar_one())


async def _ai_table_snapshot(world: World) -> tuple[set[UUID], set[UUID]]:
    documents = await world.session.execute(select(AIDocument.id))
    chunks = await world.session.execute(select(AIChunk.id))
    return set(documents.scalars()), set(chunks.scalars())


def _run(*, grant_lab: bool, body: Callable[[World], Awaitable[None]]) -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            await body(await _build_world(session, grant_lab=grant_lab))

    asyncio.run(scenario())


def test_hidden_record_is_excluded_from_doctor_search_and_visible_score_is_unchanged() -> None:
    async def body(world: World) -> None:
        before = await world.query_service.search(
            world.doctor, patient_id=world.patient_id, query="glucose diabetes"
        )
        before_scores = {chunk.record_id: chunk.score for chunk in before}
        assert set(before_scores) == {world.lab_hidden.id, world.lab_visible.id}

        await _set_hidden(world, world.lab_hidden, True)

        after = await world.query_service.search(
            world.doctor, patient_id=world.patient_id, query="glucose diabetes"
        )
        assert [chunk.record_id for chunk in after] == [world.lab_visible.id]
        assert after[0].score == before_scores[world.lab_visible.id]
        assert all("fasting" not in chunk.content for chunk in after)

    _run(grant_lab=True, body=body)


def test_hidden_record_is_excluded_from_generation_context_and_citations() -> None:
    async def body(world: World) -> None:
        await _set_hidden(world, world.lab_hidden, True)
        generator = FakeAnswerGenerator()

        answer = await world.query_service.generate_answer(
            world.doctor,
            patient_id=world.patient_id,
            query="glucose diabetes",
            category_codes=world.category_codes,
            generator=generator,
        )

        assert len(generator.calls) == 1
        context_records = {item.record_id for item in generator.calls[0].items}
        assert context_records == {world.lab_visible.id}
        assert {citation.record_id for citation in answer.citations} == {world.lab_visible.id}
        assert await _summary_audit_count(world) == 1

    _run(grant_lab=True, body=body)


def test_records_outside_granted_categories_stay_excluded_hidden_or_not() -> None:
    async def body(world: World) -> None:
        visible_results = await world.query_service.search(
            world.doctor, patient_id=world.patient_id, query="metformin glucose"
        )
        assert world.rx.id not in {chunk.record_id for chunk in visible_results}
        assert all(chunk.category_id == world.cat_lab for chunk in visible_results)

        await _set_hidden(world, world.rx, True)
        hidden_results = await world.query_service.search(
            world.doctor, patient_id=world.patient_id, query="metformin"
        )
        assert hidden_results == []

    _run(grant_lab=True, body=body)


def test_no_consent_still_yields_no_evidence() -> None:
    async def body(world: World) -> None:
        assert (
            await world.query_service.search(
                world.doctor, patient_id=world.patient_id, query="glucose diabetes"
            )
            == []
        )
        generator = FakeAnswerGenerator()
        answer = await world.query_service.generate_answer(
            world.doctor,
            patient_id=world.patient_id,
            query="glucose diabetes",
            category_codes=world.category_codes,
            generator=generator,
        )
        assert answer.answer == DEFAULT_EMPTY_EVIDENCE_ANSWER
        assert generator.calls == []
        assert await _summary_audit_count(world) == 0

    _run(grant_lab=False, body=body)


def test_patient_copilot_keeps_owner_access_to_hidden_records() -> None:
    async def body(world: World) -> None:
        await _set_hidden(world, world.lab_hidden, True)
        generator = FakeAnswerGenerator()

        await world.query_service.generate_self_answer(
            world.patient,
            patient_id=world.patient_id,
            query="glucose diabetes",
            category_codes=world.category_codes,
            generator=generator,
        )

        assert len(generator.calls) == 1
        context_records = {item.record_id for item in generator.calls[0].items}
        assert context_records == {world.lab_hidden.id, world.lab_visible.id, world.rx.id}

    # The patient path needs no grant; the doctor's grant must not matter either way.
    _run(grant_lab=False, body=body)


def test_hiding_and_unhiding_after_indexing_takes_effect_without_reindexing() -> None:
    async def body(world: World) -> None:
        indexed = await _ai_table_snapshot(world)

        async def doctor_records() -> set[UUID]:
            results = await world.query_service.search(
                world.doctor, patient_id=world.patient_id, query="fasting panel"
            )
            return {chunk.record_id for chunk in results}

        assert world.lab_hidden.id in await doctor_records()

        await _set_hidden(world, world.lab_hidden, True)
        assert world.lab_hidden.id not in await doctor_records()
        assert await _ai_table_snapshot(world) == indexed

        await _set_hidden(world, world.lab_hidden, False)
        assert world.lab_hidden.id in await doctor_records()
        assert await _ai_table_snapshot(world) == indexed

    _run(grant_lab=True, body=body)


def test_all_matching_doctor_evidence_hidden_returns_empty_evidence_without_generation() -> None:
    async def body(world: World) -> None:
        await _set_hidden(world, world.lab_hidden, True)
        await _set_hidden(world, world.lab_visible, True)
        generator = FakeAnswerGenerator()

        answer = await world.query_service.generate_answer(
            world.doctor,
            patient_id=world.patient_id,
            query="glucose diabetes",
            category_codes=world.category_codes,
            generator=generator,
        )

        assert answer.answer == DEFAULT_EMPTY_EVIDENCE_ANSWER
        assert answer.citations == ()
        assert generator.calls == []
        assert await _summary_audit_count(world) == 0

    _run(grant_lab=True, body=body)


def test_grantee_repository_query_filters_hidden_while_owner_query_does_not() -> None:
    async def body(world: World) -> None:
        await _set_hidden(world, world.lab_hidden, True)
        scope = frozenset({world.cat_lab, world.cat_rx})
        owner_docs = await world.ai_repository.search_chunks(
            patient_id=world.patient_id, category_ids=scope
        )
        grantee_docs = await world.ai_repository.search_grantee_chunks(
            patient_id=world.patient_id, category_ids=scope
        )
        assert len(owner_docs) == 3
        assert len(grantee_docs) == 2
        hidden_doc = await world.ai_repository.get_document_by_record_id(world.lab_hidden.id)
        assert hidden_doc is not None
        assert hidden_doc.id not in {chunk.document_id for chunk in grantee_docs}
        assert (
            await world.ai_repository.search_grantee_chunks(
                patient_id=world.patient_id, category_ids=frozenset()
            )
            == []
        )

    _run(grant_lab=True, body=body)
