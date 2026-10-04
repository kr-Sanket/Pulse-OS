import asyncio
from uuid import uuid4

from app.modules.ai.models import AIDocument, AIChunk
from app.modules.ai.service import AIIngestionService


class FakeAIRepository:
    def __init__(self) -> None:
        self.documents: dict = {}
        self.chunks: list[AIChunk] = []

    async def get_document_by_record_id(self, record_id):
        return self.documents.get(record_id)

    async def add_document(self, document: AIDocument):
        self.documents[document.record_id] = document
        return document

    async def add_chunks(self, chunks):
        self.chunks.extend(chunks)
        return chunks


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