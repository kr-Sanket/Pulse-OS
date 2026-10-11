import asyncio
from datetime import date
from uuid import uuid4

from app.modules.ai.models import AIChunk, AIDocument
from app.modules.ai.repository import AIRepository
from app.modules.auth.domain import Role
from app.modules.auth.models import User
from app.modules.patients.models import Patient
from app.modules.records.models import MedicalRecord, RecordCategory, RecordOrigin
from tests.support import sqlite_session


def test_ai_repository_persists_document_and_chunks() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            category = RecordCategory(
                code="LAB_REPORT",
                display_name="Lab Report",
            )
            session.add(category)
            await session.flush()

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

            patient_id = patient.id
            record_id = uuid4()

            record = MedicalRecord(
                id=record_id,
                patient_id=patient_id,
                category_id=category.id,
                origin=RecordOrigin.PATIENT_LOCKER,
                uploaded_by_hospital_id=None,
                uploaded_by_doctor_id=None,
                date_of_service=date(2026, 1, 1),
                description="Test record",
                original_filename="test.json",
                content_type="application/fhir+json",
                size_bytes=100,
                s3_key=f"records/{patient_id}/{record_id}",
            )
            session.add(record)
            await session.flush()

            repository = AIRepository(session)

            document = AIDocument(
                record_id=record_id,
                patient_id=patient_id,
                category_id=category.id,
                content_hash="a" * 64,
                source_version=1,
            )

            await repository.add_document(document)

            chunks = [
                AIChunk(
                    document_id=document.id,
                    patient_id=patient_id,
                    category_id=category.id,
                    chunk_index=0,
                    content="first chunk",
                    content_hash="b" * 64,
                    token_count=2,
                ),
                AIChunk(
                    document_id=document.id,
                    patient_id=patient_id,
                    category_id=category.id,
                    chunk_index=1,
                    content="second chunk",
                    content_hash="c" * 64,
                    token_count=2,
                ),
            ]

            await repository.add_chunks(chunks)

            found = await repository.get_document_by_record_id(record_id)

            assert found is not None
            assert found.id == document.id
            assert found.record_id == record_id
            assert found.content_hash == "a" * 64
            assert found.source_version == 1

            assert len(chunks) == 2
            assert chunks[0].document_id == document.id
            assert chunks[1].document_id == document.id

    asyncio.run(scenario())


def test_get_document_by_id() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            category = RecordCategory(
                code="LAB_REPORT",
                display_name="Lab Report",
            )
            session.add(category)
            await session.flush()

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

            record_id = uuid4()

            record = MedicalRecord(
                id=record_id,
                patient_id=patient.id,
                category_id=category.id,
                origin=RecordOrigin.PATIENT_LOCKER,
                uploaded_by_hospital_id=None,
                uploaded_by_doctor_id=None,
                date_of_service=date(2026, 1, 1),
                description="Test record",
                original_filename="test.json",
                content_type="application/fhir+json",
                size_bytes=100,
                s3_key=f"records/{patient.id}/{record_id}",
            )
            session.add(record)
            await session.flush()

            document = AIDocument(
                record_id=record_id,
                patient_id=patient.id,
                category_id=category.id,
                content_hash="a" * 64,
                source_version=1,
            )
            session.add(document)
            await session.flush()

            repository = AIRepository(session)

            result = await repository.get_document_by_id(document.id)

            assert result is not None
            assert result.id == document.id
            assert result.record_id == record_id

    asyncio.run(scenario())
