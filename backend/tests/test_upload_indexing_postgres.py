"""Upload indexing under real concurrency on PostgreSQL (opt-in, like the other *_postgres files).

Skipped unless ``PULSEOS_TEST_POSTGRES_URL`` names a scratch database; each run works only in
its own uniquely named schema and drops it afterwards. What SQLite cannot show: two deliveries
of the same job on separate connections, racing to insert the one ``ai_documents`` row — the
UNIQUE on ``record_id`` must leave exactly one document and one set of chunks, and neither
delivery may fail.
"""

import asyncio
import datetime as dt
from uuid import UUID, uuid4

import pytest
from app.modules.ai.models import AIChunk, AIDocument
from app.modules.auth.domain import Role
from app.modules.auth.models import User
from app.modules.patients.models import Patient
from app.modules.records.fake import FakeObjectStorage
from app.modules.records.models import (
    MedicalRecord,
    RecordCategory,
    RecordOrigin,
    RecordProcessingStatus,
)
from app.modules.records.upload_indexing import IndexingOutcome, UploadIndexingService
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from tests.pdf_fixtures import text_pdf
from tests.test_audit_batches_postgres import POSTGRES_URL, _scratch_schema

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL.startswith("postgresql"),
    reason="PostgreSQL tests are opt-in: set PULSEOS_TEST_POSTGRES_URL to a scratch database",
)


async def _seed(engine: AsyncEngine, storage: FakeObjectStorage) -> UUID:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        user = User(firebase_uid=f"fb-{uuid4()}", role=Role.PATIENT)
        session.add(user)
        await session.flush()
        patient = Patient(user_id=user.id, health_id="PHI-IND-2026-1QE8DVR", full_name="P")
        category = RecordCategory(code="LAB_REPORT", display_name="Lab report")
        session.add_all([patient, category])
        await session.flush()
        data = text_pdf(["Ferritin 8 ng/mL low", "Haemoglobin 9.8 g/dL"])
        record = MedicalRecord(
            patient_id=patient.id,
            category_id=category.id,
            origin=RecordOrigin.PATIENT_LOCKER,
            date_of_service=dt.date(2026, 9, 1),
            original_filename="labs.pdf",
            content_type="application/pdf",
            size_bytes=len(data),
            s3_key=f"records/{patient.id}/{uuid4()}",
        )
        session.add(record)
        await session.flush()
        await storage.put_object(record.s3_key, data, content_type="application/pdf")
        return record.id


def test_concurrent_deliveries_index_once_and_neither_fails() -> None:
    async def scenario() -> None:
        async with _scratch_schema() as engine:
            storage = FakeObjectStorage()
            record_id = await _seed(engine, storage)
            factory = async_sessionmaker(engine, expire_on_commit=False)

            async def deliver() -> IndexingOutcome:
                async with factory() as session, session.begin():
                    result = await UploadIndexingService(session, storage).index_uploaded_record(
                        record_id, final_attempt=False
                    )
                    return result.outcome

            outcomes = await asyncio.gather(*(deliver() for _ in range(4)))

            assert outcomes.count(IndexingOutcome.INDEXED) == 1
            assert set(outcomes) <= {IndexingOutcome.INDEXED, IndexingOutcome.ALREADY_INDEXED}
            async with factory() as session:
                documents = await session.execute(
                    select(func.count())
                    .select_from(AIDocument)
                    .where(AIDocument.record_id == record_id)
                )
                assert documents.scalar_one() == 1
                chunks = await session.execute(
                    select(AIChunk.chunk_index)
                    .join(AIDocument, AIDocument.id == AIChunk.document_id)
                    .where(AIDocument.record_id == record_id)
                )
                indices = list(chunks.scalars())
                assert indices and len(indices) == len(set(indices))  # no duplicated chunks
                record = await session.get(MedicalRecord, record_id)
                assert record is not None
                assert record.processing_status is RecordProcessingStatus.INDEXED

    asyncio.run(scenario())
