import asyncio
from typing import Any
from uuid import uuid4

from app.modules.ai.ingestion import AIRecordIngestion
from app.modules.ai.service import AIIngestionService


class FakeAIRepository:
    def __init__(self) -> None:
        self.documents: dict[Any, Any] = {}
        self.chunks: list[Any] = []

    async def get_document_by_record_id(self, record_id: Any) -> Any:
        return self.documents.get(record_id)

    async def add_document(self, document: Any) -> Any:
        self.documents[document.record_id] = document
        return document

    async def add_chunks(self, chunks: list[Any]) -> list[Any]:
        self.chunks.extend(chunks)
        return chunks

    async def delete_chunks_by_document_id(self, document_id: Any) -> None:
        self.chunks = [c for c in self.chunks if c.document_id != document_id]


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


def test_fhir_bytes_resource_is_parsed_and_indexed():
    import json

    repository = FakeAIRepository()
    service = AIIngestionService(repository)
    ingestion = AIRecordIngestion(service)

    record_id = uuid4()
    patient_id = uuid4()
    category_id = uuid4()

    resource = {
        "resourceType": "Condition",
        "id": "condition-bytes",
        "status": "active",
        "code": {"text": "Hypertension"},
    }
    raw_bytes = json.dumps(resource).encode("utf-8")

    document = asyncio.run(
        ingestion.index_fhir_resource(
            record_id=record_id,
            patient_id=patient_id,
            category_id=category_id,
            resource=raw_bytes,
        )
    )

    assert document is not None
    assert len(repository.documents) == 1
    assert "Hypertension" in repository.chunks[0].content


def test_diagnostic_report_ingestion_contains_analytes_and_dates():
    repository = FakeAIRepository()
    service = AIIngestionService(repository)
    ingestion = AIRecordIngestion(service)

    record_id = uuid4()
    patient_id = uuid4()
    category_id = uuid4()

    resource = {
        "resourceType": "DiagnosticReport",
        "id": "dr-bmp-01",
        "status": "final",
        "effectiveDateTime": "2026-04-01T10:00:00Z",
        "code": {"text": "Basic Metabolic Panel"},
        "result": [
            {
                "resourceType": "Observation",
                "code": {"text": "Glucose"},
                "valueQuantity": {"value": 69.5, "unit": "mg/dL"},
            },
            {
                "resourceType": "Observation",
                "code": {"text": "Creatinine"},
                "valueQuantity": {"value": 1.0, "unit": "mg/dL"},
            },
        ],
    }

    document = asyncio.run(
        ingestion.index_fhir_resource(
            record_id=record_id,
            patient_id=patient_id,
            category_id=category_id,
            resource=resource,
        )
    )

    assert document is not None
    combined = " ".join(chunk.content for chunk in repository.chunks)
    assert "Effective Date: 2026-04-01T10:00:00Z" in combined
    assert "Result: Glucose 69.5 mg/dL" in combined
    assert "Result: Creatinine 1 mg/dL" in combined


def test_reindexing_with_changed_content_replaces_chunks_and_keeps_document():
    repository = FakeAIRepository()
    service = AIIngestionService(repository)
    ingestion = AIRecordIngestion(service)

    record_id = uuid4()
    patient_id = uuid4()
    category_id = uuid4()

    resource_v1 = {
        "resourceType": "DiagnosticReport",
        "id": "dr-reindex",
        "status": "final",
        "code": {"text": "Panel A"},
        "result": [
            {"code": {"text": "Glucose"}, "valueQuantity": {"value": 70.0, "unit": "mg/dL"}},
        ],
    }

    doc_v1 = asyncio.run(
        ingestion.index_fhir_resource(
            record_id=record_id,
            patient_id=patient_id,
            category_id=category_id,
            resource=resource_v1,
        )
    )
    assert doc_v1 is not None
    assert len(repository.documents) == 1
    assert len(repository.chunks) == 1
    assert "Glucose 70 mg/dL" in repository.chunks[0].content
    initial_hash = doc_v1.content_hash

    # Reindexing with identical content -> no-op
    doc_noop = asyncio.run(
        ingestion.index_fhir_resource(
            record_id=record_id,
            patient_id=patient_id,
            category_id=category_id,
            resource=resource_v1,
            reindex=True,
        )
    )
    assert doc_noop is None
    assert len(repository.documents) == 1
    assert len(repository.chunks) == 1

    # Reindexing with changed content -> updates document, replaces chunks
    resource_v2 = {
        "resourceType": "DiagnosticReport",
        "id": "dr-reindex",
        "status": "final",
        "code": {"text": "Panel A"},
        "result": [
            {"code": {"text": "Glucose"}, "valueQuantity": {"value": 85.0, "unit": "mg/dL"}},
            {"code": {"text": "Potassium"}, "valueQuantity": {"value": 4.5, "unit": "mmol/L"}},
        ],
    }

    doc_v2 = asyncio.run(
        ingestion.index_fhir_resource(
            record_id=record_id,
            patient_id=patient_id,
            category_id=category_id,
            resource=resource_v2,
            reindex=True,
        )
    )
    assert doc_v2 is not None
    assert doc_v2.id == doc_v1.id
    assert doc_v2.content_hash != initial_hash
    assert len(repository.documents) == 1

    combined_v2 = " ".join(c.content for c in repository.chunks)
    assert "Glucose 85 mg/dL" in combined_v2
    assert "Potassium 4.5 mmol/L" in combined_v2
    assert "Glucose 70 mg/dL" not in combined_v2
