"""HTTP router tests for GET /api/v1/ai/patients/{patient_id}/search."""

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.ai.dependencies import get_ai_query_service
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
