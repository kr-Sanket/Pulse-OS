import asyncio
from collections.abc import Collection
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from app.modules.ai.models import AIChunk, AIDocument
from app.modules.ai.service import (
    AIIngestionService,
    AIRetrievalService,
    RetrievalVisibility,
)


class FakeAIRepository:
    def __init__(self) -> None:
        self.documents: dict = {}
        self.chunks: list[AIChunk] = []

    async def get_document_by_record_id(self, record_id):
        return self.documents.get(record_id)

    async def add_document(self, document: AIDocument):
        if getattr(document, "id", None) is None:
            document.id = uuid4()
        self.documents[document.record_id] = document
        return document

    async def add_chunks(self, chunks):
        self.chunks.extend(chunks)
        return chunks

    async def get_document_by_id(self, document_id):
        for document in self.documents.values():
            if document.id == document_id:
                return document
        return None

    async def search_chunks(self, *, patient_id, category_ids):
        return [
            chunk
            for chunk in self.chunks
            if chunk.patient_id == patient_id
            and chunk.category_id in category_ids
        ]


def test_index_record_creates_document_and_chunks():
    repository = FakeAIRepository()
    service = AIIngestionService(repository)

    record_id = uuid4()
    patient_id = uuid4()
    category_id = uuid4()

    document = asyncio.run(
        service.index_record(
            record_id=record_id,
            patient_id=patient_id,
            category_id=category_id,
            normalized_text="one two three four five",
            max_tokens=2,
        )
    )

    assert document is not None
    assert document.record_id == record_id
    assert document.patient_id == patient_id
    assert document.category_id == category_id
    assert document.source_version == 1

    assert len(repository.documents) == 1
    assert len(repository.chunks) == 3

    assert repository.chunks[0].chunk_index == 0
    assert repository.chunks[0].content == "one two"
    assert repository.chunks[0].token_count == 2

    assert repository.chunks[1].chunk_index == 1
    assert repository.chunks[1].content == "three four"

    assert repository.chunks[2].chunk_index == 2
    assert repository.chunks[2].content == "five"
    assert repository.chunks[2].token_count == 1

    assert all(
        chunk.document_id == document.id
        for chunk in repository.chunks
    )


def test_index_record_is_idempotent():
    repository = FakeAIRepository()
    service = AIIngestionService(repository)

    record_id = uuid4()
    patient_id = uuid4()
    category_id = uuid4()

    first = asyncio.run(
        service.index_record(
            record_id=record_id,
            patient_id=patient_id,
            category_id=category_id,
            normalized_text="one two three four",
            max_tokens=2,
        )
    )

    second = asyncio.run(
        service.index_record(
            record_id=record_id,
            patient_id=patient_id,
            category_id=category_id,
            normalized_text="different content",
            max_tokens=2,
        )
    )

    assert first is not None
    assert second is None

    assert len(repository.documents) == 1
    assert len(repository.chunks) == 2

    assert repository.chunks[0].content == "one two"
    assert repository.chunks[1].content == "three four"

def test_retrieval_service_returns_ranked_consent_scoped_chunks():
    repository = FakeAIRepository()
    ingestion = AIIngestionService(repository)

    patient_id = uuid4()
    allowed_category_id = uuid4()
    other_category_id = uuid4()

    first_document = asyncio.run(
        ingestion.index_record(
            record_id=uuid4(),
            patient_id=patient_id,
            category_id=allowed_category_id,
            normalized_text="diabetes active condition",
            max_tokens=20,
        )
    )

    second_document = asyncio.run(
        ingestion.index_record(
            record_id=uuid4(),
            patient_id=patient_id,
            category_id=allowed_category_id,
            normalized_text="diabetes diabetes active condition",
            max_tokens=20,
        )
    )

    asyncio.run(
        ingestion.index_record(
            record_id=uuid4(),
            patient_id=patient_id,
            category_id=other_category_id,
            normalized_text="diabetes diabetes diabetes",
            max_tokens=20,
        )
    )

    service = AIRetrievalService(repository)

    results = asyncio.run(
        service.search(
            patient_id=patient_id,
            category_ids=frozenset({allowed_category_id}),
            query="diabetes active",
            visibility=RetrievalVisibility.OWNER,
            limit=10,
        )
    )

    assert len(results) == 2

    # More matching query terms → higher score.
    assert results[0].score == 2
    assert results[1].score == 2

    # Only the authorized category is searched.
    assert all(
        result.category_id == allowed_category_id
        for result in results
    )

    assert results[0].record_id in {
        first_document.record_id,
        second_document.record_id,
    }


class FakeDateLookup:
    def __init__(self, dates: dict[UUID, date]) -> None:
        self.dates = dates
        self.call_count = 0
        self.requested_batches: list[Collection[UUID]] = []

    async def dates_by_record_ids(self, record_ids: Collection[UUID]) -> dict[UUID, date]:
        self.call_count += 1
        self.requested_batches.append(record_ids)
        return {rid: self.dates[rid] for rid in record_ids if rid in self.dates}


def test_t5_batched_date_lookup_single_query_and_correct_mapping() -> None:
    repository: Any = FakeAIRepository()
    ingestion = AIIngestionService(repository)

    patient_id = uuid4()
    cat_id = uuid4()
    record_id_1 = uuid4()
    record_id_2 = uuid4()

    asyncio.run(
        ingestion.index_record(
            record_id=record_id_1,
            patient_id=patient_id,
            category_id=cat_id,
            normalized_text="diagnosticreport lab result",
            max_tokens=20,
        )
    )
    asyncio.run(
        ingestion.index_record(
            record_id=record_id_2,
            patient_id=patient_id,
            category_id=cat_id,
            normalized_text="diagnosticreport lab result",
            max_tokens=20,
        )
    )

    date_lookup = FakeDateLookup({
        record_id_1: date(2018, 10, 1),
        # record_id_2 intentionally missing from lookup to test missing ID resilience
    })

    service = AIRetrievalService(repository, date_lookup=date_lookup)

    results = asyncio.run(
        service.search(
            patient_id=patient_id,
            category_ids=frozenset({cat_id}),
            query="lab result",
            visibility=RetrievalVisibility.OWNER,
            limit=10,
        )
    )

    # Batched lookup called exactly once for all retrieved records (no N+1)
    assert date_lookup.call_count == 1
    assert set(date_lookup.requested_batches[0]) == {record_id_1, record_id_2}

    # Correct date mappings on results
    r1 = next(r for r in results if r.record_id == record_id_1)
    assert r1.date_of_service == date(2018, 10, 1)

    r2 = next(r for r in results if r.record_id == record_id_2)
    assert r2.date_of_service is None


def test_t1_retrieval_service_temporal_query_prioritizes_newer_record() -> None:
    repository: Any = FakeAIRepository()
    ingestion = AIIngestionService(repository)

    patient_id = uuid4()
    cat_id = uuid4()
    rec_old = uuid4()
    rec_new = uuid4()

    asyncio.run(
        ingestion.index_record(
            record_id=rec_old,
            patient_id=patient_id,
            category_id=cat_id,
            normalized_text="diagnosticreport panel laboratory result",
            max_tokens=20,
        )
    )
    asyncio.run(
        ingestion.index_record(
            record_id=rec_new,
            patient_id=patient_id,
            category_id=cat_id,
            normalized_text="diagnosticreport panel laboratory result",
            max_tokens=20,
        )
    )

    date_lookup = FakeDateLookup({
        rec_old: date(2017, 9, 24),
        rec_new: date(2018, 10, 1),
    })

    service = AIRetrievalService(repository, date_lookup=date_lookup)

    results = asyncio.run(
        service.search(
            patient_id=patient_id,
            category_ids=frozenset({cat_id}),
            query="What are the patient's latest laboratory results?",
            visibility=RetrievalVisibility.OWNER,
            limit=10,
        )
    )

    assert len(results) == 2
    assert results[0].record_id == rec_new
    assert results[0].date_of_service == date(2018, 10, 1)
    assert results[1].record_id == rec_old
    assert results[1].date_of_service == date(2017, 9, 24)
