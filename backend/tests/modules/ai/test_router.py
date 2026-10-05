"""HTTP router tests for AI search and answer endpoints."""

from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.ai.context import AssembledContext
from app.modules.ai.dependencies import get_ai_query_service, get_answer_generator
from app.modules.ai.generation import FakeAnswerGenerator, GeneratedAnswer
from app.modules.ai.providers.gemini import (
    GeminiProviderError,
    GeminiRateLimitError,
    GeminiResponseError,
    GeminiSafetyError,
    GeminiTimeoutError,
    GeminiUnavailableError,
)
from app.modules.ai.query import AIQueryService
from app.modules.ai.retrieval import RetrievedChunk
from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.auth.fake import FakeAuthProvider
from app.modules.consent.dependencies import (
    CategoryVocabulary,
    get_category_vocabulary,
    get_category_vocabulary_source,
)
from tests.support import FakeCategoryVocabularySource


DEFAULT_CATEGORY_ID = UUID("11111111-1111-1111-1111-111111111111")
DEFAULT_CATEGORY_CODE = "LAB_REPORT"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class FakeAIQueryService:
    """In-memory fake replacing AIQueryService in HTTP router tests."""

    def __init__(self, results: list[RetrievedChunk] | None = None) -> None:
        self.results = results if results is not None else []
        self.calls: list[dict[str, Any]] = []

    async def search(
        self,
        requester: AuthenticatedUser,
        *,
        patient_id: UUID,
        query: str,
        limit: int = 10,
    ) -> list[RetrievedChunk]:
        self.calls.append(
            {
                "requester": requester,
                "patient_id": patient_id,
                "query": query,
                "limit": limit,
            }
        )
        return self.results


@pytest.fixture
def fake_query_service(app: FastAPI) -> Iterator[FakeAIQueryService]:
    service = FakeAIQueryService()
    app.dependency_overrides[get_ai_query_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_ai_query_service, None)


@pytest.fixture(autouse=True)
def fake_category_vocabulary(app: FastAPI) -> Iterator[CategoryVocabulary]:
    source = FakeCategoryVocabularySource({DEFAULT_CATEGORY_CODE: DEFAULT_CATEGORY_ID})
    app.dependency_overrides[get_category_vocabulary_source] = lambda: source
    app.dependency_overrides[get_category_vocabulary] = lambda: source._vocabulary
    yield source._vocabulary
    app.dependency_overrides.pop(get_category_vocabulary_source, None)
    app.dependency_overrides.pop(get_category_vocabulary, None)


def test_successful_doctor_request_returns_retrieval_results(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    fake_query_service: FakeAIQueryService,
) -> None:
    doctor_id = uuid4()
    patient_id = uuid4()
    token = "doctor-token"
    fake_auth.register_user(
        token,
        user_id=doctor_id,
        firebase_uid="fb-doctor-1",
        role=Role.DOCTOR,
    )

    chunk = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        record_id=uuid4(),
        patient_id=patient_id,
        category_id=DEFAULT_CATEGORY_ID,
        chunk_index=0,
        content="Patient diagnosed with Type 2 Diabetes",
        content_hash="d5a84b1234567890",
        token_count=6,
        score=2,
    )
    fake_query_service.results = [chunk]

    response = client.get(
        f"/api/v1/ai/patients/{patient_id}/search?query=diabetes",
        headers=_bearer(token),
    )

    assert response.status_code == 200
    assert len(fake_query_service.calls) == 1
    assert fake_query_service.calls[0]["patient_id"] == patient_id
    assert fake_query_service.calls[0]["query"] == "diabetes"
    assert fake_query_service.calls[0]["requester"].user_id == doctor_id
    assert fake_query_service.calls[0]["requester"].role == Role.DOCTOR

    data = response.json()
    assert "items" in data
    assert isinstance(data["items"], list)
    assert len(data["items"]) == 1

    item = data["items"][0]
    assert item == {
        "chunkId": str(chunk.chunk_id),
        "recordId": str(chunk.record_id),
        "categoryCode": DEFAULT_CATEGORY_CODE,
        "chunkIndex": chunk.chunk_index,
        "content": chunk.content,
        "tokenCount": chunk.token_count,
    }

    # Verify internal fields are NOT exposed
    assert "documentId" not in item
    assert "document_id" not in item
    assert "categoryId" not in item
    assert "category_id" not in item
    assert "contentHash" not in item
    assert "content_hash" not in item
    assert "score" not in item


@pytest.mark.parametrize("role", [Role.PATIENT, Role.HOSPITAL_ADMIN, Role.SYSTEM_ADMIN])
def test_non_doctor_role_is_rejected_with_403(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    fake_query_service: FakeAIQueryService,
    role: Role,
) -> None:
    token = f"{role.value.lower()}-token"
    fake_auth.register_user(
        token,
        user_id=uuid4(),
        firebase_uid=f"fb-{token}",
        role=role,
    )
    patient_id = uuid4()

    response = client.get(
        f"/api/v1/ai/patients/{patient_id}/search?query=diabetes",
        headers=_bearer(token),
    )

    assert response.status_code == 403
    assert len(fake_query_service.calls) == 0


def test_unauthenticated_request_is_rejected_with_401(
    client: TestClient,
    fake_query_service: FakeAIQueryService,
) -> None:
    patient_id = uuid4()
    response = client.get(
        f"/api/v1/ai/patients/{patient_id}/search?query=diabetes",
    )

    assert response.status_code == 401
    assert len(fake_query_service.calls) == 0


def test_empty_query_is_rejected_with_422(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    fake_query_service: FakeAIQueryService,
) -> None:
    token = "doctor-token"
    fake_auth.register_user(
        token,
        user_id=uuid4(),
        firebase_uid="fb-doctor-empty",
        role=Role.DOCTOR,
    )
    patient_id = uuid4()

    # Empty string query parameter
    response_empty = client.get(
        f"/api/v1/ai/patients/{patient_id}/search?query=",
        headers=_bearer(token),
    )
    assert response_empty.status_code == 422
    assert len(fake_query_service.calls) == 0

    # Missing query parameter entirely
    response_missing = client.get(
        f"/api/v1/ai/patients/{patient_id}/search",
        headers=_bearer(token),
    )
    assert response_missing.status_code == 422
    assert len(fake_query_service.calls) == 0


def test_query_longer_than_500_chars_is_rejected_with_422(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    fake_query_service: FakeAIQueryService,
) -> None:
    token = "doctor-token"
    fake_auth.register_user(
        token,
        user_id=uuid4(),
        firebase_uid="fb-doctor-long",
        role=Role.DOCTOR,
    )
    patient_id = uuid4()
    long_query = "a" * 501

    response = client.get(
        f"/api/v1/ai/patients/{patient_id}/search?query={long_query}",
        headers=_bearer(token),
    )
    assert response.status_code == 422
    assert len(fake_query_service.calls) == 0


def test_query_at_max_boundary_of_500_chars_is_accepted(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    fake_query_service: FakeAIQueryService,
) -> None:
    token = "doctor-token"
    fake_auth.register_user(
        token,
        user_id=uuid4(),
        firebase_uid="fb-doctor-max",
        role=Role.DOCTOR,
    )
    patient_id = uuid4()
    max_query = "a" * 500

    response = client.get(
        f"/api/v1/ai/patients/{patient_id}/search?query={max_query}",
        headers=_bearer(token),
    )
    assert response.status_code == 200
    assert len(fake_query_service.calls) == 1
    assert fake_query_service.calls[0]["query"] == max_query


# ==============================================================================
# Phase A4.8 Tests: POST /api/v1/ai/patients/{patient_id}/answer
# ==============================================================================


class FakeConsentScope:
    def __init__(self, granted_categories: frozenset[UUID] | None = None) -> None:
        self.granted_categories = (
            granted_categories if granted_categories is not None else frozenset()
        )
        self.calls: list[dict[str, Any]] = []

    async def granted_category_ids(
        self, requester: AuthenticatedUser, *, patient_id: UUID, at: datetime
    ) -> frozenset[UUID]:
        self.calls.append({"requester": requester, "patient_id": patient_id, "at": at})
        return self.granted_categories


class FakeRetrieval:
    def __init__(self, chunks: list[RetrievedChunk] | None = None) -> None:
        self.chunks = chunks if chunks is not None else []
        self.calls: list[dict[str, Any]] = []

    async def search(
        self,
        *,
        patient_id: UUID,
        category_ids: frozenset[UUID],
        query: str,
        limit: int = 10,
    ) -> list[RetrievedChunk]:
        self.calls.append(
            {
                "patient_id": patient_id,
                "category_ids": category_ids,
                "query": query,
                "limit": limit,
            }
        )
        if not category_ids:
            return []
        return [c for c in self.chunks if c.category_id in category_ids][:limit]


class FakeSummaryAuditor:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def record_summary_generated(
        self,
        requester: AuthenticatedUser,
        *,
        patient_id: UUID,
        at: datetime,
        request_context: str | None = None,
    ) -> None:
        self.events.append(
            {
                "requester": requester,
                "patient_id": patient_id,
                "at": at,
                "request_context": request_context,
            }
        )


class ErrorAnswerGenerator:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls: list[AssembledContext] = []

    async def generate_answer(self, context: AssembledContext) -> GeneratedAnswer:
        self.calls.append(context)
        raise self.exc


def test_doctor_with_valid_consent_returns_generated_answer(
    client: TestClient,
    app: FastAPI,
    fake_auth: FakeAuthProvider,
) -> None:
    doctor_id = uuid4()
    patient_id = uuid4()
    token = "doctor-token"
    fake_auth.register_user(
        token,
        user_id=doctor_id,
        firebase_uid="fb-doctor-answer-1",
        role=Role.DOCTOR,
    )

    record_id = uuid4()
    chunk = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        record_id=record_id,
        patient_id=patient_id,
        category_id=DEFAULT_CATEGORY_ID,
        chunk_index=0,
        content="Patient has fasting glucose of 105 mg/dL.",
        content_hash="hash123",
        token_count=8,
        score=5,
    )

    fake_consent = FakeConsentScope(frozenset({DEFAULT_CATEGORY_ID}))
    fake_retrieval = FakeRetrieval([chunk])
    fake_auditor = FakeSummaryAuditor()
    real_service = AIQueryService(
        retrieval=fake_retrieval,  # type: ignore[arg-type]
        consent=fake_consent,
        auditor=fake_auditor,
    )
    fake_generator = FakeAnswerGenerator(
        answer_template="Patient exhibits fasting glucose of 105 mg/dL [1]."
    )

    app.dependency_overrides[get_ai_query_service] = lambda: real_service
    app.dependency_overrides[get_answer_generator] = lambda: fake_generator
    try:
        response = client.post(
            f"/api/v1/ai/patients/{patient_id}/answer",
            json={"query": "What is the fasting blood glucose?"},
            headers={**_bearer(token), "X-Request-Id": "req-answer-42"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["answer"] == "Patient exhibits fasting glucose of 105 mg/dL [1]."
        assert data["provider"] == "fake"
        assert data["model"] == "fake-v1"
        assert "disclaimer" in data and len(data["disclaimer"]) > 0

        assert len(data["citations"]) == 1
        citation = data["citations"][0]
        assert citation == {
            "citationIndex": 1,
            "recordId": str(record_id),
            "categoryCode": DEFAULT_CATEGORY_CODE,
            "chunkIndex": 0,
        }

        # Verify sensitive internal fields are NOT exposed
        for forbidden in (
            "chunkId",
            "documentId",
            "categoryId",
            "contentHash",
            "s3Key",
            "score",
            "firebaseUid",
            "apiKey",
        ):
            assert forbidden not in data
            assert forbidden not in citation

        # Verify SUMMARY_GENERATED audit event was recorded
        assert len(fake_auditor.events) == 1
        event = fake_auditor.events[0]
        assert event["requester"].user_id == doctor_id
        assert event["requester"].role == Role.DOCTOR
        assert event["patient_id"] == patient_id
        assert event["request_context"] == "req-answer-42"
    finally:
        app.dependency_overrides.pop(get_ai_query_service, None)
        app.dependency_overrides.pop(get_answer_generator, None)


def test_doctor_without_consent_returns_empty_evidence_answer(
    client: TestClient,
    app: FastAPI,
    fake_auth: FakeAuthProvider,
) -> None:
    doctor_id = uuid4()
    patient_id = uuid4()
    token = "doctor-token"
    fake_auth.register_user(
        token,
        user_id=doctor_id,
        firebase_uid="fb-doctor-no-consent",
        role=Role.DOCTOR,
    )

    chunk = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        record_id=uuid4(),
        patient_id=patient_id,
        category_id=DEFAULT_CATEGORY_ID,
        chunk_index=0,
        content="Patient has fasting glucose of 105 mg/dL.",
        content_hash="hash123",
        token_count=8,
        score=5,
    )

    # Empty consent scope: no grants
    fake_consent = FakeConsentScope(frozenset())
    fake_retrieval = FakeRetrieval([chunk])
    fake_auditor = FakeSummaryAuditor()
    real_service = AIQueryService(
        retrieval=fake_retrieval,  # type: ignore[arg-type]
        consent=fake_consent,
        auditor=fake_auditor,
    )
    fake_generator = FakeAnswerGenerator()

    app.dependency_overrides[get_ai_query_service] = lambda: real_service
    app.dependency_overrides[get_answer_generator] = lambda: fake_generator
    try:
        response = client.post(
            f"/api/v1/ai/patients/{patient_id}/answer",
            json={"query": "What is the fasting blood glucose?"},
            headers=_bearer(token),
        )

        assert response.status_code == 200
        data = response.json()
        assert (
            data["answer"]
            == "The available medical records do not contain information regarding the requested topic."
        )
        assert data["citations"] == []

        # Generator must NOT have been called
        assert len(fake_generator.calls) == 0

        # SUMMARY_GENERATED audit must NOT have been recorded
        assert len(fake_auditor.events) == 0
    finally:
        app.dependency_overrides.pop(get_ai_query_service, None)
        app.dependency_overrides.pop(get_answer_generator, None)


def test_revoked_consent_returns_empty_evidence_answer(
    client: TestClient,
    app: FastAPI,
    fake_auth: FakeAuthProvider,
) -> None:
    doctor_id = uuid4()
    patient_id = uuid4()
    token = "doctor-token"
    fake_auth.register_user(
        token,
        user_id=doctor_id,
        firebase_uid="fb-doctor-revoked",
        role=Role.DOCTOR,
    )

    # Revoked grant results in empty granted_category_ids
    fake_consent = FakeConsentScope(frozenset())
    fake_retrieval = FakeRetrieval([])
    fake_auditor = FakeSummaryAuditor()
    real_service = AIQueryService(
        retrieval=fake_retrieval,  # type: ignore[arg-type]
        consent=fake_consent,
        auditor=fake_auditor,
    )
    fake_generator = FakeAnswerGenerator()

    app.dependency_overrides[get_ai_query_service] = lambda: real_service
    app.dependency_overrides[get_answer_generator] = lambda: fake_generator
    try:
        response = client.post(
            f"/api/v1/ai/patients/{patient_id}/answer",
            json={"query": "What is the blood pressure history?"},
            headers=_bearer(token),
        )

        assert response.status_code == 200
        data = response.json()
        assert (
            data["answer"]
            == "The available medical records do not contain information regarding the requested topic."
        )
        assert data["citations"] == []
        assert len(fake_generator.calls) == 0
        assert len(fake_auditor.events) == 0
    finally:
        app.dependency_overrides.pop(get_ai_query_service, None)
        app.dependency_overrides.pop(get_answer_generator, None)


def test_empty_retrieval_result_does_not_invoke_generator(
    client: TestClient,
    app: FastAPI,
    fake_auth: FakeAuthProvider,
) -> None:
    doctor_id = uuid4()
    patient_id = uuid4()
    token = "doctor-token"
    fake_auth.register_user(
        token,
        user_id=doctor_id,
        firebase_uid="fb-doctor-empty-res",
        role=Role.DOCTOR,
    )

    # Active consent exists, but lexical search returns 0 matching chunks
    fake_consent = FakeConsentScope(frozenset({DEFAULT_CATEGORY_ID}))
    fake_retrieval = FakeRetrieval([])
    fake_auditor = FakeSummaryAuditor()
    real_service = AIQueryService(
        retrieval=fake_retrieval,  # type: ignore[arg-type]
        consent=fake_consent,
        auditor=fake_auditor,
    )
    fake_generator = FakeAnswerGenerator()

    app.dependency_overrides[get_ai_query_service] = lambda: real_service
    app.dependency_overrides[get_answer_generator] = lambda: fake_generator
    try:
        response = client.post(
            f"/api/v1/ai/patients/{patient_id}/answer",
            json={"query": "Unrelated medical search term"},
            headers=_bearer(token),
        )

        assert response.status_code == 200
        data = response.json()
        assert (
            data["answer"]
            == "The available medical records do not contain information regarding the requested topic."
        )
        assert data["citations"] == []
        assert len(fake_generator.calls) == 0
        assert len(fake_auditor.events) == 0
    finally:
        app.dependency_overrides.pop(get_ai_query_service, None)
        app.dependency_overrides.pop(get_answer_generator, None)


def test_citation_provenance_preserves_multiple_records(
    client: TestClient,
    app: FastAPI,
    fake_auth: FakeAuthProvider,
) -> None:
    doctor_id = uuid4()
    patient_id = uuid4()
    token = "doctor-token"
    fake_auth.register_user(
        token,
        user_id=doctor_id,
        firebase_uid="fb-doctor-citations",
        role=Role.DOCTOR,
    )

    rec1 = uuid4()
    rec2 = uuid4()
    chunk1 = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        record_id=rec1,
        patient_id=patient_id,
        category_id=DEFAULT_CATEGORY_ID,
        chunk_index=0,
        content="Lab 1 report content.",
        content_hash="h1",
        token_count=5,
        score=10,
    )
    chunk2 = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        record_id=rec2,
        patient_id=patient_id,
        category_id=DEFAULT_CATEGORY_ID,
        chunk_index=1,
        content="Lab 2 report content.",
        content_hash="h2",
        token_count=5,
        score=8,
    )

    fake_consent = FakeConsentScope(frozenset({DEFAULT_CATEGORY_ID}))
    fake_retrieval = FakeRetrieval([chunk1, chunk2])
    fake_auditor = FakeSummaryAuditor()
    real_service = AIQueryService(
        retrieval=fake_retrieval,  # type: ignore[arg-type]
        consent=fake_consent,
        auditor=fake_auditor,
    )
    fake_generator = FakeAnswerGenerator()

    app.dependency_overrides[get_ai_query_service] = lambda: real_service
    app.dependency_overrides[get_answer_generator] = lambda: fake_generator
    try:
        response = client.post(
            f"/api/v1/ai/patients/{patient_id}/answer",
            json={"query": "summarize labs"},
            headers=_bearer(token),
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["citations"]) == 2
        assert data["citations"][0] == {
            "citationIndex": 1,
            "recordId": str(rec1),
            "categoryCode": DEFAULT_CATEGORY_CODE,
            "chunkIndex": 0,
        }
        assert data["citations"][1] == {
            "citationIndex": 2,
            "recordId": str(rec2),
            "categoryCode": DEFAULT_CATEGORY_CODE,
            "chunkIndex": 1,
        }
    finally:
        app.dependency_overrides.pop(get_ai_query_service, None)
        app.dependency_overrides.pop(get_answer_generator, None)


@pytest.mark.parametrize(
    "error_exc,expected_status",
    [
        (GeminiRateLimitError("Rate limit exceeded"), 429),
        (GeminiTimeoutError("Request deadline exceeded"), 504),
        (GeminiUnavailableError("Service unavailable"), 503),
        (GeminiSafetyError("Safety violation"), 422),
        (GeminiResponseError("Invalid JSON structure"), 502),
        (GeminiProviderError("General provider failure"), 502),
    ],
)
def test_failed_generation_error_mappings(
    client: TestClient,
    app: FastAPI,
    fake_auth: FakeAuthProvider,
    error_exc: Exception,
    expected_status: int,
) -> None:
    doctor_id = uuid4()
    patient_id = uuid4()
    token = "doctor-token"
    fake_auth.register_user(
        token,
        user_id=doctor_id,
        firebase_uid="fb-doctor-err",
        role=Role.DOCTOR,
    )

    chunk = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        record_id=uuid4(),
        patient_id=patient_id,
        category_id=DEFAULT_CATEGORY_ID,
        chunk_index=0,
        content="Lab data.",
        content_hash="h1",
        token_count=3,
        score=2,
    )

    fake_consent = FakeConsentScope(frozenset({DEFAULT_CATEGORY_ID}))
    fake_retrieval = FakeRetrieval([chunk])
    fake_auditor = FakeSummaryAuditor()
    real_service = AIQueryService(
        retrieval=fake_retrieval,  # type: ignore[arg-type]
        consent=fake_consent,
        auditor=fake_auditor,
    )
    error_generator = ErrorAnswerGenerator(error_exc)

    app.dependency_overrides[get_ai_query_service] = lambda: real_service
    app.dependency_overrides[get_answer_generator] = lambda: error_generator
    try:
        response = client.post(
            f"/api/v1/ai/patients/{patient_id}/answer",
            json={"query": "test query"},
            headers=_bearer(token),
        )

        assert response.status_code == expected_status
        # On error, NO SUMMARY_GENERATED audit event must be committed
        assert len(fake_auditor.events) == 0
    finally:
        app.dependency_overrides.pop(get_ai_query_service, None)
        app.dependency_overrides.pop(get_answer_generator, None)


@pytest.mark.parametrize("role", [Role.PATIENT, Role.HOSPITAL_ADMIN, Role.SYSTEM_ADMIN])
def test_non_doctor_roles_cannot_invoke_answer_endpoint(
    client: TestClient,
    fake_auth: FakeAuthProvider,
    role: Role,
) -> None:
    token = f"{role.value.lower()}-token"
    fake_auth.register_user(
        token,
        user_id=uuid4(),
        firebase_uid=f"fb-{token}",
        role=role,
    )
    patient_id = uuid4()

    response = client.post(
        f"/api/v1/ai/patients/{patient_id}/answer",
        json={"query": "diabetes"},
        headers=_bearer(token),
    )

    assert response.status_code == 403


def test_unauthenticated_request_to_answer_endpoint_returns_401(
    client: TestClient,
) -> None:
    patient_id = uuid4()
    response = client.post(
        f"/api/v1/ai/patients/{patient_id}/answer",
        json={"query": "diabetes"},
    )
    assert response.status_code == 401


def test_request_validation_for_answer_endpoint(
    client: TestClient,
    app: FastAPI,
    fake_auth: FakeAuthProvider,
) -> None:
    doctor_id = uuid4()
    patient_id = uuid4()
    token = "doctor-token"
    fake_auth.register_user(
        token,
        user_id=doctor_id,
        firebase_uid="fb-doctor-validation",
        role=Role.DOCTOR,
    )

    fake_consent = FakeConsentScope(frozenset({DEFAULT_CATEGORY_ID}))
    fake_retrieval = FakeRetrieval([])
    real_service = AIQueryService(
        retrieval=fake_retrieval,  # type: ignore[arg-type]
        consent=fake_consent,
    )
    fake_generator = FakeAnswerGenerator()

    app.dependency_overrides[get_ai_query_service] = lambda: real_service
    app.dependency_overrides[get_answer_generator] = lambda: fake_generator
    try:
        # Empty query
        res = client.post(
            f"/api/v1/ai/patients/{patient_id}/answer",
            json={"query": ""},
            headers=_bearer(token),
        )
        assert res.status_code == 422

        # Query > 500 chars
        res = client.post(
            f"/api/v1/ai/patients/{patient_id}/answer",
            json={"query": "a" * 501},
            headers=_bearer(token),
        )
        assert res.status_code == 422

        # max_tokens <= 0
        res = client.post(
            f"/api/v1/ai/patients/{patient_id}/answer",
            json={"query": "valid query", "maxTokens": 0},
            headers=_bearer(token),
        )
        assert res.status_code == 422

        # max_tokens > 4000
        res = client.post(
            f"/api/v1/ai/patients/{patient_id}/answer",
            json={"query": "valid query", "maxTokens": 4001},
            headers=_bearer(token),
        )
        assert res.status_code == 422

        # Extra forbidden field (extra="forbid")
        res = client.post(
            f"/api/v1/ai/patients/{patient_id}/answer",
            json={"query": "valid query", "unknownField": "not_allowed"},
            headers=_bearer(token),
        )
        assert res.status_code == 422

        # Query at boundary 500 chars is accepted
        res = client.post(
            f"/api/v1/ai/patients/{patient_id}/answer",
            json={"query": "a" * 500},
            headers=_bearer(token),
        )
        assert res.status_code == 200
    finally:
        app.dependency_overrides.pop(get_ai_query_service, None)
        app.dependency_overrides.pop(get_answer_generator, None)


def test_unconfigured_gemini_provider_returns_503(
    client: TestClient,
    app: FastAPI,
    fake_auth: FakeAuthProvider,
) -> None:
    doctor_id = uuid4()
    patient_id = uuid4()
    token = "doctor-token"
    fake_auth.register_user(
        token,
        user_id=doctor_id,
        firebase_uid="fb-doctor-unconfigured",
        role=Role.DOCTOR,
    )

    from app.modules.ai.dependencies import AIConfigurationError

    def unconfigured_generator() -> Any:
        raise AIConfigurationError()

    app.dependency_overrides[get_answer_generator] = unconfigured_generator
    try:
        response = client.post(
            f"/api/v1/ai/patients/{patient_id}/answer",
            json={"query": "diabetes"},
            headers=_bearer(token),
        )
        assert response.status_code == 503
        data = response.json()
        assert data["detail"] == "AI answer generation service is unconfigured."
    finally:
        app.dependency_overrides.pop(get_answer_generator, None)


