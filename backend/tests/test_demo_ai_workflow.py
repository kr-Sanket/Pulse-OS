"""Demo workflow D — AI record assistant over an uploaded PDF, end to end (docs/DEMO_GUIDE.md).

Upload → worker indexing → question → answer with citations, through the mounted application
and the real ``record_uploaded`` worker task (ADR-033). Faked: auth, object storage, the job
queue (its enqueued jobs are replayed into the worker task by hand, as arq would deliver
them) and the answer generator — a scripted stand-in for Ollama, since no live model runs in
tests. Everything between the HTTP request and the generator is real: consent scope,
hidden-record filtering, context assembly, citation reconciliation, post-answer consent
revalidation and audit.

Pinned here as one sequence; the narrower rules have their own suites
(``test_upload_indexing.py``, ``tests/modules/ai/``, ``test_consent_revocation_atomicity.py``).
"""

import asyncio
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from app.core.db import create_session_factory, get_db_session
from app.core.queue import InMemoryJobQueue
from app.modules.ai.context import AssembledContext
from app.modules.ai.dependencies import get_answer_generator
from app.modules.ai.generation import CitationReference, GeneratedAnswer
from app.modules.ai.query import DEFAULT_EMPTY_EVIDENCE_ANSWER
from app.modules.auth.domain import Role
from app.modules.auth.fake import FakeAuthProvider
from app.modules.auth.models import User
from app.modules.consent.models import ConsentGrant
from app.modules.patients.seed import seed_synthetic_patients
from app.modules.records.fake import FakeObjectStorage
from app.modules.records.seed import seed_demo_staff, seed_reference_data
from app.workers.tasks import record_uploaded
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.pdf_fixtures import blank_pdf, text_pdf
from tests.support import run_with_session

RECORDS = "/api/v1/records"
REQUESTS = "/api/v1/access-requests"
GRANTS = "/api/v1/consent-grants"
GRANTED_RECORDS = "/api/v1/granted-records"
AUDIT = "/api/v1/audit-logs"
COPILOT = "/api/v1/ai/me/answer"

HEALTH_ID = "PHI-IND-2026-1QE8DVR"  # Aarav Sharma (Demo), seed_synthetic_patients
DEMO_DOCTOR_UID = "synthetic:doctor:hid-0002"  # Dr. Thomas George (Demo), CMC Vellore
LAB_LINES = [
    "Synthetic lab report for demo use only",
    "Haemoglobin 9.8 g/dL low",
    "Serum ferritin 8 ng/mL markedly low",
    "Impression iron deficiency anaemia",
]
QUESTION = "What was the serum ferritin result?"
MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


@dataclass
class ScriptedGenerator:
    """Stands in for Ollama: answers from the evidence it is given, with one valid marker
    and one marker naming evidence that was never supplied, plus a bogus citation claim —
    the two things ``reconcile_citations`` must strip. ``during`` runs mid-generation
    (used to revoke consent while the "model" is working)."""

    calls: list[AssembledContext] = field(default_factory=list)
    during: Callable[[], Any] | None = None

    async def generate_answer(self, context: AssembledContext) -> GeneratedAnswer:
        self.calls.append(context)
        if self.during is not None:
            await self.during()
        first = context.items[0]
        return GeneratedAnswer(
            answer="Serum ferritin was 8 ng/mL, markedly low [1]. Consistent with iron "
            "deficiency [1, 9]. An unsupported aside [9].",
            citations=(
                CitationReference(1, first.record_id, first.category_code, first.chunk_index),
                CitationReference(9, uuid4(), "MRI", 0),  # names nothing that was supplied
            ),
            provider="scripted",
            model="scripted-v1",
            generated_at=datetime.now(UTC),
        )


@dataclass
class Demo:
    patient: dict[str, str]
    doctor: dict[str, str]
    generator: ScriptedGenerator
    session_holder: list[AsyncSession]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def demo(
    app: FastAPI,
    client: TestClient,
    fake_auth: FakeAuthProvider,
    sqlite_db: None,
    db_engine: AsyncEngine,
    fake_storage: FakeObjectStorage,
    fake_queue: InMemoryJobQueue,
) -> Demo:
    async def arrange(session: AsyncSession) -> dict[str, UUID]:
        await seed_reference_data(session)
        await seed_demo_staff(session)
        await seed_synthetic_patients(session)

        async def user_id(uid: str) -> UUID:
            row = await session.execute(select(User.id).where(User.firebase_uid == uid))
            return row.scalar_one()

        return {
            "patient": await user_id("synthetic:patient:aarav"),
            "doctor": await user_id(DEMO_DOCTOR_UID),
        }

    ids = run_with_session(db_engine, arrange)
    fake_auth.register_user(
        "patient", user_id=ids["patient"], firebase_uid="synthetic:patient:aarav", role=Role.PATIENT
    )
    fake_auth.register_user(
        "doctor", user_id=ids["doctor"], firebase_uid=DEMO_DOCTOR_UID, role=Role.DOCTOR
    )

    # Same per-request session semantics as ``sqlite_db``, but the live session is kept so a
    # generator can change state inside the request it is serving (the revocation race).
    factory = create_session_factory(db_engine)
    holder: list[AsyncSession] = []

    async def session_per_request() -> AsyncIterator[AsyncSession]:
        async with factory() as session, session.begin():
            holder[:] = [session]
            yield session

    app.dependency_overrides[get_db_session] = session_per_request
    generator = ScriptedGenerator()
    app.dependency_overrides[get_answer_generator] = lambda: generator
    return Demo(_bearer("patient"), _bearer("doctor"), generator, holder)


def _upload(client: TestClient, demo: Demo, name: str, data: bytes, content_type: str) -> str:
    response: httpx.Response = client.post(
        RECORDS,
        data={"categoryCode": "LAB_REPORT", "dateOfService": "2026-09-01"},
        files={"file": (name, data, content_type)},
        headers=demo.patient,
    )
    assert response.status_code == 201, response.text
    assert response.json()["processingStatus"] == "UPLOADED"
    return str(response.json()["id"])


def _run_worker(
    queue: InMemoryJobQueue, engine: AsyncEngine, storage: FakeObjectStorage
) -> dict[str, str]:
    """Deliver every enqueued job to the real worker task, as arq would (first attempt)."""
    ctx: dict[str, Any] = {
        "session_factory": create_session_factory(engine),
        "storage": storage,
        "job_try": 1,
    }
    outcomes: dict[str, str] = {}
    for task, kwargs in queue.jobs:
        assert task == "record_uploaded"
        record_id = str(kwargs["record_id"])
        outcomes[record_id] = asyncio.run(record_uploaded(ctx, record_id=record_id))
    queue.jobs.clear()
    return outcomes


def _status(client: TestClient, demo: Demo, record_id: str) -> str:
    response = client.get(f"{RECORDS}/{record_id}", headers=demo.patient)
    assert response.status_code == 200, response.text
    return str(response.json()["processingStatus"])


def _assert_citations_match_markers(body: dict[str, Any]) -> set[int]:
    """Every [N] in the text has a citation, and every citation appears as [N] in the text."""
    in_text = {int(n) for group in MARKER.findall(body["answer"]) for n in group.split(",")}
    cited = {c["citationIndex"] for c in body["citations"]}
    assert in_text == cited
    return cited


def _ask_as_doctor(client: TestClient, demo: Demo, patient_id: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/ai/patients/{patient_id}/answer", json={"query": QUESTION}, headers=demo.doctor
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _trail(client: TestClient, demo: Demo) -> list[str]:
    items = client.get(AUDIT, params={"limit": 100}, headers=demo.patient).json()["items"]
    return [item["action"] for item in items]


def test_workflow_d_ai_record_assistant_end_to_end(
    client: TestClient,
    demo: Demo,
    db_engine: AsyncEngine,
    fake_storage: FakeObjectStorage,
    fake_queue: InMemoryJobQueue,
) -> None:
    # 1. The patient uploads a synthetic text-layer PDF, a scanned (text-less) PDF and a photo.
    lab = _upload(client, demo, "ferritin-demo.pdf", text_pdf(LAB_LINES), "application/pdf")
    scan = _upload(client, demo, "scan-demo.pdf", blank_pdf(), "application/pdf")
    photo = _upload(client, demo, "photo-demo.png", b"\x89PNG\r\n\x1a\nnot-ocr", "image/png")

    # 2. The worker indexes what it can and says why it could not index the rest.
    outcomes = _run_worker(fake_queue, db_engine, fake_storage)
    assert outcomes == {lab: "INDEXED", scan: "NO_TEXT", photo: "UNSUPPORTED_TYPE"}
    # This is the field both portals render (patient: "AI search" row; doctor: status badge).
    assert _status(client, demo, lab) == "INDEXED"
    assert _status(client, demo, scan) == "FAILED"
    assert _status(client, demo, photo) == "UPLOADED"

    # 3-5. The patient asks their Health Copilot; the answer cites the uploaded PDF, the
    # unsupported marker and the bogus citation claim are gone, and markers == citations.
    asked = client.post(COPILOT, json={"query": QUESTION}, headers=demo.patient)
    assert asked.status_code == 200, asked.text
    body = asked.json()
    assert body["answer"] == (
        "Serum ferritin was 8 ng/mL, markedly low [1]. Consistent with iron deficiency [1]. "
        "An unsupported aside."
    )
    assert _assert_citations_match_markers(body) == {1}
    assert body["citations"] == [
        {"citationIndex": 1, "recordId": lab, "categoryCode": "LAB_REPORT", "chunkIndex": 0}
    ]
    assert body["provider"] == "scripted" and body["disclaimer"]
    evidence = demo.generator.calls[-1].items
    assert {item.record_id for item in evidence} == {UUID(lab)}  # nothing from scan/photo
    assert "ferritin 8 ng/mL" in evidence[0].content

    # 6a. A clinician with no grant gets nothing; the model is never called.
    patient_id = client.get(
        GRANTED_RECORDS, params={"patientHealthId": HEALTH_ID}, headers=demo.doctor
    ).json()["patientId"]
    calls_before = len(demo.generator.calls)
    refused = _ask_as_doctor(client, demo, patient_id)
    assert refused["answer"] == DEFAULT_EMPTY_EVIDENCE_ANSWER
    assert refused["citations"] == []
    assert len(demo.generator.calls) == calls_before

    # The patient grants LAB_REPORT through the per-category consent flow.
    request_id = client.post(
        REQUESTS,
        json={"patientHealthId": HEALTH_ID, "categoryCodes": ["LAB_REPORT"], "purpose": "demo"},
        headers=demo.doctor,
    ).json()["id"]
    approved = client.post(
        f"{REQUESTS}/{request_id}/approve",
        json={"categoryCodes": ["LAB_REPORT"]},
        headers=demo.patient,
    )
    assert approved.status_code == 200, approved.text
    grant_id = approved.json()["grants"][0]["id"]

    # Granted: the clinician's assistant answers from the same PDF, citing it.
    granted = _ask_as_doctor(client, demo, patient_id)
    assert _assert_citations_match_markers(granted) == {1}
    assert granted["citations"][0]["recordId"] == lab

    # 6b. Hidden by the patient: gone from the clinician's evidence at once, no re-index;
    # still in the patient's own copilot.
    hide = client.patch(
        f"{RECORDS}/{lab}/visibility", json={"isHidden": True}, headers=demo.patient
    )
    assert hide.status_code == 200, hide.text
    hidden = _ask_as_doctor(client, demo, patient_id)
    assert hidden["answer"] == DEFAULT_EMPTY_EVIDENCE_ANSWER and hidden["citations"] == []
    own = client.post(COPILOT, json={"query": QUESTION}, headers=demo.patient).json()
    assert [c["recordId"] for c in own["citations"]] == [lab]
    client.patch(f"{RECORDS}/{lab}/visibility", json={"isHidden": False}, headers=demo.patient)

    # 6c. Post-answer consent revalidation: the grant is revoked while the model is
    # generating. The finished answer and its citations are discarded, not delivered.
    async def revoke_mid_generation() -> None:
        session = demo.session_holder[0]
        await session.execute(
            update(ConsentGrant)
            .where(ConsentGrant.id == UUID(grant_id))
            .values(revoked_at=datetime.now(UTC) - timedelta(seconds=1))
        )

    demo.generator.during = revoke_mid_generation
    calls_before = len(demo.generator.calls)
    raced = _ask_as_doctor(client, demo, patient_id)
    demo.generator.during = None
    assert len(demo.generator.calls) == calls_before + 1  # the model did run…
    assert raced["answer"] == DEFAULT_EMPTY_EVIDENCE_ANSWER  # …and its answer was discarded
    assert raced["citations"] == []

    # The patient's trail: one summary per delivered answer (copilot twice, clinician once).
    # Refusals: the pre-grant granted-records lookup, the pre-grant answer and the discarded
    # answer. The hidden-only attempt found no evidence and wrote nothing (documented in
    # docs/AI_ARCHITECTURE.md §Audit).
    trail = _trail(client, demo)
    assert trail.count("RECORD_UPLOADED") == 3
    assert trail.count("SUMMARY_GENERATED") == 3
    assert trail.count("ACCESS_DENIED") == 3
    assert trail[0] == "ACCESS_DENIED"  # the discarded answer is the most recent event


def test_workflow_d_a_scanned_pdf_alone_gives_the_no_evidence_answer(
    client: TestClient,
    demo: Demo,
    db_engine: AsyncEngine,
    fake_storage: FakeObjectStorage,
    fake_queue: InMemoryJobQueue,
) -> None:
    """Step 7: with only a scan uploaded there is no text to search — the record says so
    (FAILED), and the copilot answers with the fixed no-evidence sentence without calling
    the model, rather than inventing anything."""
    scan = _upload(client, demo, "scan-demo.pdf", blank_pdf(), "application/pdf")
    assert _run_worker(fake_queue, db_engine, fake_storage) == {scan: "NO_TEXT"}
    assert _status(client, demo, scan) == "FAILED"

    body = client.post(COPILOT, json={"query": QUESTION}, headers=demo.patient).json()

    assert body["answer"] == DEFAULT_EMPTY_EVIDENCE_ANSWER
    assert body["citations"] == []
    assert demo.generator.calls == []


def test_a_suspended_hospitals_clinician_keeps_ai_answers_under_an_existing_grant(
    client: TestClient,
    demo: Demo,
    db_engine: AsyncEngine,
    fake_storage: FakeObjectStorage,
    fake_queue: InMemoryJobQueue,
) -> None:
    """ADR-034: suspension stops *new* access (discovery, requests) but never what the
    patient already authorised — the clinician's AI answer still cites the granted PDF."""
    from app.modules.records.models import Hospital, HospitalVerificationStatus

    lab = _upload(client, demo, "ferritin-demo.pdf", text_pdf(LAB_LINES), "application/pdf")
    assert _run_worker(fake_queue, db_engine, fake_storage) == {lab: "INDEXED"}
    request_id = client.post(
        REQUESTS,
        json={"patientHealthId": HEALTH_ID, "categoryCodes": ["LAB_REPORT"], "purpose": "demo"},
        headers=demo.doctor,
    ).json()["id"]
    approved = client.post(
        f"{REQUESTS}/{request_id}/approve",
        json={"categoryCodes": ["LAB_REPORT"]},
        headers=demo.patient,
    )
    assert approved.status_code == 200, approved.text
    patient_id = client.get(
        GRANTED_RECORDS, params={"patientHealthId": HEALTH_ID}, headers=demo.doctor
    ).json()["patientId"]

    async def suspend_cmc(session: AsyncSession) -> None:
        await session.execute(
            update(Hospital)
            .where(Hospital.hid == "HID-0002")
            .values(verification_status=HospitalVerificationStatus.SUSPENDED)
        )

    run_with_session(db_engine, suspend_cmc)

    answer = _ask_as_doctor(client, demo, patient_id)
    assert _assert_citations_match_markers(answer) == {1}
    assert answer["citations"][0]["recordId"] == lab

    discovery = client.get(
        f"{RECORDS}/existence", params={"patientHealthId": HEALTH_ID}, headers=demo.doctor
    )
    assert discovery.status_code == 409
    renewed = client.post(
        REQUESTS,
        json={"patientHealthId": HEALTH_ID, "categoryCodes": ["MRI"], "purpose": "demo"},
        headers=demo.doctor,
    )
    assert renewed.status_code == 409
