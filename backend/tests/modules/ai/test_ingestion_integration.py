import asyncio
from uuid import uuid4

from app.modules.ai.ingestion import AIRecordIngestion
from app.modules.ai.models import AIDocument, AIChunk
from app.modules.ai.repository import AIRepository
from app.modules.ai.service import AIIngestionService
from app.modules.records.models import (
    MedicalRecord,
    RecordCategory,
    RecordOrigin,
)
from app.modules.auth.models import Role, User
from app.modules.patients.models import Patient
from tests.support import sqlite_session


def test_fhir_ingestion_persists_document_and_chunks():
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

            stored_document = await repository.get_document_by_record_id(
                record_id
            )

            assert stored_document is not None
            assert stored_document.id == document.id

            chunks_result = await session.execute(
                __import__("sqlalchemy").select(AIChunk)
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

            assert all(
                chunk.document_id == document.id
                for chunk in chunks
            )
            assert all(
                chunk.patient_id == patient.id
                for chunk in chunks
            )
            assert all(
                chunk.category_id == category.id
                for chunk in chunks
            )

    asyncio.run(scenario())