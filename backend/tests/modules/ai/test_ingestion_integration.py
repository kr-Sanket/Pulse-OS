import asyncio
from uuid import uuid4

from app.modules.ai.ingestion import AIRecordIngestion
from app.modules.ai.models import AIChunk, AIDocument
from app.modules.ai.repository import AIRepository
from app.modules.ai.service import AIIngestionService
from app.modules.auth.domain import Role
from app.modules.auth.models import User
from app.modules.patients.models import Patient
from app.modules.records.models import (
    MedicalRecord,
    RecordCategory,
    RecordOrigin,
)
from tests.support import sqlite_session


def test_fhir_ingestion_persists_document_and_chunks() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            # Create the minimum valid clinical record graph.
            user = User(
                firebase_uid=f"fb-{uuid4()}",
                role=Role.PATIENT,
            )
            session.add(user)
            await session.flush()

            patient = Patient(
                user_id=user.id,
                health_id=f"PHI-IND-2026-{str(uuid4())[:7].upper()}",
                full_name="Test Patient",
            )
            session.add(patient)
            await session.flush()

            category = RecordCategory(
                code="LAB_REPORT",
                display_name="Lab Report",
            )
            session.add(category)
            await session.flush()

            record_id = uuid4()

            record = MedicalRecord(
                id=record_id,
                patient_id=patient.id,
                category_id=category.id,
                origin=RecordOrigin.PATIENT_LOCKER,
                uploaded_by_hospital_id=None,
                uploaded_by_doctor_id=None,
                date_of_service=__import__("datetime").date(2026, 1, 1),
                description="Test FHIR record",
                original_filename="condition.json",
                content_type="application/fhir+json",
                size_bytes=100,
                s3_key=f"records/{patient.id}/{record_id}",
            )
            session.add(record)
            await session.flush()

            repository = AIRepository(session)
            service = AIIngestionService(repository)
            ingestion = AIRecordIngestion(service)

            resource = {
                "resourceType": "Condition",
                "id": "condition-001",
                "clinicalStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                            "code": "active",
                        }
                    ]
                },
                "code": {
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": "44054006",
                            "display": "Diabetes mellitus type 2",
                        }
                    ],
                    "text": "Type 2 diabetes mellitus",
                },
            }

            document = await ingestion.index_fhir_resource(
                record_id=record_id,
                patient_id=patient.id,
                category_id=category.id,
                resource=resource,
                source_version=1,
                max_tokens=20,
            )

            assert document is not None
            assert document.record_id == record_id
            assert document.patient_id == patient.id
            assert document.category_id == category.id
            assert document.source_version == 1

            stored_document = await repository.get_document_by_record_id(record_id)

            assert stored_document is not None
            assert stored_document.id == document.id

            chunks_result = await session.execute(
                __import__("sqlalchemy")
                .select(AIChunk)
                .where(AIChunk.document_id == document.id)
                .order_by(AIChunk.chunk_index)
            )
            chunks = list(chunks_result.scalars())

            assert chunks
            combined_content = " ".join(chunk.content for chunk in chunks)

            assert "Resource Type: Condition" in combined_content
            assert "Resource ID: condition-001" in combined_content
            assert "Clinical Status" in combined_content
            assert "active" in combined_content
            assert "Type 2 diabetes mellitus" in combined_content

            assert all(chunk.document_id == document.id for chunk in chunks)
            assert all(chunk.patient_id == patient.id for chunk in chunks)
            assert all(chunk.category_id == category.id for chunk in chunks)

    asyncio.run(scenario())


def test_diagnostic_report_ingestion_and_reindex_integration() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            user = User(
                firebase_uid=f"fb-{uuid4()}",
                role=Role.PATIENT,
            )
            session.add(user)
            await session.flush()

            patient = Patient(
                user_id=user.id,
                health_id=f"PHI-IND-2026-{str(uuid4())[:7].upper()}",
                full_name="Lab Patient",
            )
            session.add(patient)
            await session.flush()

            category = RecordCategory(
                code="LAB_REPORT",
                display_name="Lab Report",
            )
            session.add(category)
            await session.flush()

            record_id = uuid4()

            record = MedicalRecord(
                id=record_id,
                patient_id=patient.id,
                category_id=category.id,
                origin=RecordOrigin.PATIENT_LOCKER,
                uploaded_by_hospital_id=None,
                uploaded_by_doctor_id=None,
                date_of_service=__import__("datetime").date(2026, 4, 1),
                description="Basic Metabolic Panel",
                original_filename="lab.json",
                content_type="application/fhir+json",
                size_bytes=200,
                s3_key=f"records/{patient.id}/{record_id}",
            )
            session.add(record)
            await session.flush()

            repository = AIRepository(session)
            service = AIIngestionService(repository)
            ingestion = AIRecordIngestion(service)

            resource = {
                "resourceType": "DiagnosticReport",
                "id": "dr-bmp-001",
                "status": "final",
                "effectiveDateTime": "2026-04-01T08:30:00Z",
                "code": {
                    "text": "Basic Metabolic Panel",
                    "coding": [
                        {
                            "code": "24323-8",
                            "display": "Basic Metabolic Panel",
                            "system": "http://loinc.org",
                        }
                    ],
                },
                "result": [
                    {
                        "resourceType": "Observation",
                        "code": {"text": "Glucose"},
                        "valueQuantity": {"value": 69.53, "unit": "mg/dL"},
                    },
                    {
                        "resourceType": "Observation",
                        "code": {"text": "Creatinine"},
                        "valueQuantity": {"value": 1.0, "unit": "mg/dL"},
                    },
                ],
            }

            # 1. Initial ingestion
            document = await ingestion.index_fhir_resource(
                record_id=record_id,
                patient_id=patient.id,
                category_id=category.id,
                resource=resource,
                source_version=1,
                max_tokens=50,
            )

            assert document is not None
            initial_hash = document.content_hash

            chunks_result = await session.execute(
                __import__("sqlalchemy")
                .select(AIChunk)
                .where(AIChunk.document_id == document.id)
                .order_by(AIChunk.chunk_index)
            )
            chunks = list(chunks_result.scalars())
            combined = " ".join(c.content for c in chunks)
            assert "Effective Date: 2026-04-01T08:30:00Z" in combined
            assert "Result: Glucose 69.5 mg/dL" in combined
            assert "Result: Creatinine 1 mg/dL" in combined

            # 2. Idempotent re-indexing with identical content
            noop_doc = await ingestion.index_fhir_resource(
                record_id=record_id,
                patient_id=patient.id,
                category_id=category.id,
                resource=resource,
                reindex=True,
            )
            assert noop_doc is None

            # 3. Re-indexing with updated analyte value
            updated_resource = {
                **resource,
                "result": [
                    {
                        "resourceType": "Observation",
                        "code": {"text": "Glucose"},
                        "valueQuantity": {"value": 75.0, "unit": "mg/dL"},
                    },
                    {
                        "resourceType": "Observation",
                        "code": {"text": "Creatinine"},
                        "valueQuantity": {"value": 1.0, "unit": "mg/dL"},
                    },
                ],
            }

            reindexed_doc = await ingestion.index_fhir_resource(
                record_id=record_id,
                patient_id=patient.id,
                category_id=category.id,
                resource=updated_resource,
                reindex=True,
            )
            assert reindexed_doc is not None
            assert reindexed_doc.id == document.id
            assert reindexed_doc.content_hash != initial_hash

            # Verify obsolete chunks were deleted and new chunks exist
            updated_chunks_result = await session.execute(
                __import__("sqlalchemy")
                .select(AIChunk)
                .where(AIChunk.document_id == document.id)
                .order_by(AIChunk.chunk_index)
            )
            updated_chunks = list(updated_chunks_result.scalars())
            updated_combined = " ".join(c.content for c in updated_chunks)
            assert "Result: Glucose 75 mg/dL" in updated_combined
            assert "Glucose 69.5 mg/dL" not in updated_combined

            # Verify document count in table is exactly 1
            docs_result = await session.execute(
                __import__("sqlalchemy").select(AIDocument).where(AIDocument.record_id == record_id)
            )
            assert len(list(docs_result.scalars())) == 1

    asyncio.run(scenario())
