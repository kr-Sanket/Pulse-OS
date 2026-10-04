import asyncio
from uuid import uuid4

from app.modules.ai.ingestion import AIRecordIngestion
from app.modules.ai.service import AIIngestionService


class FakeAIRepository:
    def __init__(self) -> None:
        self.documents = {}
        self.chunks = []

    async def get_document_by_record_id(self, record_id):
        return self.documents.get(record_id)

    async def add_document(self, document):
        self.documents[document.record_id] = document
        return document

    async def add_chunks(self, chunks):
        self.chunks.extend(chunks)
        return chunks


def test_fhir_resource_is_normalized_and_indexed():
    repository = FakeAIRepository()
    service = AIIngestionService(repository)
    ingestion = AIRecordIngestion(service)

    record_id = uuid4()
    patient_id = uuid4()
    category_id = uuid4()

    resource = {
        "resourceType": "Condition",
        "id": "condition-001",
        "status": "active",
        "code": {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "123456",
                    "display": "Example condition",
                }
            ]
        },
    }

    document = asyncio.run(
        ingestion.index_fhir_resource(
            record_id=record_id,
            patient_id=patient_id,
            category_id=category_id,
            resource=resource,
            max_tokens=3,
        )
    )

    assert document is not None
    assert document.record_id == record_id
    assert document.patient_id == patient_id
    assert document.category_id == category_id

    assert len(repository.documents) == 1
    assert len(repository.chunks) > 0

    combined = " ".join(chunk.content for chunk in repository.chunks)

    assert "Resource Type: Condition" in combined
    assert "Resource ID: condition-001" in combined
    assert "Status: active" in combined
    assert "Example condition" in combined


def test_empty_fhir_resource_is_not_indexed():
    repository = FakeAIRepository()
    service = AIIngestionService(repository)
    ingestion = AIRecordIngestion(service)

    document = asyncio.run(
        ingestion.index_fhir_resource(
            record_id=uuid4(),
            patient_id=uuid4(),
            category_id=uuid4(),
            resource={},
        )
    )

    assert document is None
    assert repository.documents == {}
    assert repository.chunks == []