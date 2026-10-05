import asyncio
from uuid import UUID, uuid4

import pytest

from app.modules.ai.context import AssembledContext
from app.modules.ai.query import AIQueryService
from app.modules.ai.retrieval import RetrievedChunk


class FakeConsentScope:
    def __init__(self, category_ids):
        self.category_ids = category_ids
        self.calls: list[dict[str, object]] = []

    async def granted_category_ids(self, requester, *, patient_id, at):
        self.calls.append(
            {
                "requester": requester,
                "patient_id": patient_id,
                "at": at,
            }
        )
        return self.category_ids


class FakeRetrieval:
    def __init__(self, results: list[RetrievedChunk] | None = None):
        self.calls: list[dict[str, object]] = []
        self.results: list[RetrievedChunk] = results if results is not None else []

    async def search(
        self,
        *,
        patient_id,
        category_ids,
        query,
        limit,
    ):
        self.calls.append(
            {
                "patient_id": patient_id,
                "category_ids": category_ids,
                "query": query,
                "limit": limit,
            }
        )
        return self.results[:limit]


def make_chunk(
    *,
    chunk_id: UUID | None = None,
    document_id: UUID | None = None,
    record_id: UUID | None = None,
    patient_id: UUID | None = None,
    category_id: UUID | None = None,
    chunk_index: int = 0,
    content: str = "Test chunk",
    content_hash: str = "hash",
    token_count: int = 20,
    score: int = 5,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id or uuid4(),
        document_id=document_id or uuid4(),
        record_id=record_id or uuid4(),
        patient_id=patient_id or uuid4(),
        category_id=category_id or uuid4(),
        chunk_index=chunk_index,
        content=content,
        content_hash=content_hash,
        token_count=token_count,
        score=score,
    )


def test_ai_query_service_passes_consent_scope_to_retrieval():
    consent = FakeConsentScope(frozenset({uuid4(), uuid4()}))
    retrieval = FakeRetrieval()

    service = AIQueryService(
        retrieval=retrieval,
        consent=consent,
    )

    patient_id = uuid4()
    requester = object()

    asyncio.run(
        service.search(
            requester,
            patient_id=patient_id,
            query="diabetes",
            limit=5,
        )
    )

    assert len(consent.calls) == 1
    assert len(retrieval.calls) == 1

    assert retrieval.calls[0]["patient_id"] == patient_id
    assert retrieval.calls[0]["category_ids"] == consent.category_ids
    assert retrieval.calls[0]["query"] == "diabetes"
    assert retrieval.calls[0]["limit"] == 5


def test_ai_query_service_returns_no_results_without_consent_scope():
    consent = FakeConsentScope(frozenset())
    retrieval = FakeRetrieval()

    service = AIQueryService(
        retrieval=retrieval,
        consent=consent,
    )

    patient_id = uuid4()
    requester = object()

    results = asyncio.run(
        service.search(
            requester,
            patient_id=patient_id,
            query="diabetes",
            limit=10,
        )
    )

    assert results == []

    # Retrieval must still be called with the empty authorized scope.
    assert len(retrieval.calls) == 1
    assert retrieval.calls[0]["category_ids"] == frozenset()


def test_ai_query_service_assemble_context_success():
    cat_id_1 = uuid4()
    cat_id_2 = uuid4()
    category_codes = {cat_id_1: "LAB_REPORT", cat_id_2: "PRESCRIPTION"}

    chunk1 = make_chunk(
        category_id=cat_id_1,
        content="Blood glucose 105 mg/dL",
        token_count=30,
        chunk_index=0,
    )
    chunk2 = make_chunk(
        category_id=cat_id_2,
        content="Metformin 500mg daily",
        token_count=20,
        chunk_index=1,
    )

    consent = FakeConsentScope(frozenset({cat_id_1, cat_id_2}))
    retrieval = FakeRetrieval(results=[chunk1, chunk2])

    service = AIQueryService(retrieval=retrieval, consent=consent)
    patient_id = uuid4()
    requester = object()

    context = asyncio.run(
        service.assemble_context(
            requester,
            patient_id=patient_id,
            query="glucose metformin",
            category_codes=category_codes,
            limit=5,
            max_tokens=500,
        )
    )

    assert isinstance(context, AssembledContext)
    assert context.query == "glucose metformin"
    assert context.patient_id == patient_id
    assert len(context.items) == 2
    assert context.total_tokens == 50
    assert context.max_tokens == 500
    assert context.is_truncated is False
    assert context.dropped_chunk_count == 0

    assert context.items[0].chunk_id == chunk1.chunk_id
    assert context.items[0].record_id == chunk1.record_id
    assert context.items[0].category_code == "LAB_REPORT"
    assert context.items[0].content == "Blood glucose 105 mg/dL"
    assert context.items[0].citation_index == 1

    assert context.items[1].chunk_id == chunk2.chunk_id
    assert context.items[1].record_id == chunk2.record_id
    assert context.items[1].category_code == "PRESCRIPTION"
    assert context.items[1].content == "Metformin 500mg daily"
    assert context.items[1].citation_index == 2


def test_ai_query_service_assemble_context_parameter_forwarding():
    cat_id = uuid4()
    consent = FakeConsentScope(frozenset({cat_id}))
    retrieval = FakeRetrieval(results=[])

    service = AIQueryService(retrieval=retrieval, consent=consent)
    patient_id = uuid4()
    requester = object()

    context = asyncio.run(
        service.assemble_context(
            requester,
            patient_id=patient_id,
            query="hypertension followup",
            category_codes={cat_id: "CONSULTATION_NOTE"},
            limit=7,
            max_tokens=750,
        )
    )

    # Retrieval receives forwarded search arguments through self.search
    assert len(retrieval.calls) == 1
    assert retrieval.calls[0]["patient_id"] == patient_id
    assert retrieval.calls[0]["query"] == "hypertension followup"
    assert retrieval.calls[0]["limit"] == 7

    # AssembledContext retains forwarded context arguments
    assert context.patient_id == patient_id
    assert context.query == "hypertension followup"
    assert context.max_tokens == 750


def test_ai_query_service_assemble_context_empty_retrieval():
    cat_id = uuid4()
    consent = FakeConsentScope(frozenset({cat_id}))
    retrieval = FakeRetrieval(results=[])

    service = AIQueryService(retrieval=retrieval, consent=consent)
    patient_id = uuid4()
    requester = object()

    context = asyncio.run(
        service.assemble_context(
            requester,
            patient_id=patient_id,
            query="nonexistent term",
            category_codes={cat_id: "LAB_REPORT"},
            max_tokens=1000,
        )
    )

    assert context.items == ()
    assert context.total_tokens == 0
    assert context.is_truncated is False
    assert context.dropped_chunk_count == 0


def test_ai_query_service_assemble_context_truncation():
    cat_id = uuid4()
    chunk1 = make_chunk(category_id=cat_id, token_count=50)
    chunk2 = make_chunk(category_id=cat_id, token_count=60)  # 50 + 60 = 110 > 100
    chunk3 = make_chunk(category_id=cat_id, token_count=10)

    consent = FakeConsentScope(frozenset({cat_id}))
    retrieval = FakeRetrieval(results=[chunk1, chunk2, chunk3])

    service = AIQueryService(retrieval=retrieval, consent=consent)
    patient_id = uuid4()
    requester = object()

    context = asyncio.run(
        service.assemble_context(
            requester,
            patient_id=patient_id,
            query="budget test",
            category_codes={cat_id: "LAB_REPORT"},
            max_tokens=100,
        )
    )

    assert len(context.items) == 1
    assert context.items[0].chunk_id == chunk1.chunk_id
    assert context.total_tokens == 50
    assert context.is_truncated is True
    assert context.dropped_chunk_count == 2


def test_ai_query_service_assemble_context_missing_category_mapping_raises_key_error():
    unmapped_cat_id = uuid4()
    chunk = make_chunk(category_id=unmapped_cat_id, token_count=20)

    consent = FakeConsentScope(frozenset({unmapped_cat_id}))
    retrieval = FakeRetrieval(results=[chunk])

    service = AIQueryService(retrieval=retrieval, consent=consent)
    patient_id = uuid4()
    requester = object()

    with pytest.raises(KeyError):
        asyncio.run(
            service.assemble_context(
                requester,
                patient_id=patient_id,
                query="missing cat test",
                category_codes={},  # Empty mapping lacks unmapped_cat_id
                max_tokens=500,
            )
        )