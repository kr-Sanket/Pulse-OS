"""Uploaded-record AI indexing (records/upload_indexing.py, workers/tasks.py).

Pins: text-layer PDFs are indexed and become searchable only within the existing consent,
visibility and ownership rules; images and text-less, encrypted or unparseable PDFs are never
indexed and say why through ``processing_status``; re-delivery and concurrent delivery never
duplicate chunks; storage outages are retried and only the final attempt records FAILED; no
document text reaches the log.
"""

import asyncio
import logging
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.core.db import create_session_factory
from app.core.logging import configure_logging
from app.modules.ai.models import AIChunk, AIDocument
from app.modules.ai.repository import AIRepository
from app.modules.records.errors import StorageUnavailableError
from app.modules.records.fake import FakeObjectStorage
from app.modules.records.models import MedicalRecord, RecordOrigin, RecordProcessingStatus
from app.modules.records.upload_indexing import (
    IndexingOutcome,
    UploadIndexingService,
    backfill_uploaded_records,
)
from app.workers.tasks import MAX_TRIES, record_uploaded
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.pdf_fixtures import blank_pdf, encrypted_pdf, text_pdf
from tests.support import sqlite_session
from tests.test_consent_revocation_atomicity import World, _setup_world

SECRET_LINE = "Ferritin 8 ng/mL markedly low"
PDF_TEXT = ["Haemoglobin 9.8 g/dL low", SECRET_LINE]


async def _add_record(
    session: AsyncSession,
    world: World,
    storage: FakeObjectStorage,
    *,
    data: bytes,
    content_type: str = "application/pdf",
    category_id: UUID | None = None,
    hidden: bool = False,
) -> MedicalRecord:
    record_id = uuid4()
    record = MedicalRecord(
        id=record_id,
        patient_id=world.patient.id,
        category_id=category_id or world.cat_condition.id,
        origin=RecordOrigin.PATIENT_LOCKER,
        date_of_service=date(2026, 9, 1),
        original_filename="labs.pdf",
        content_type=content_type,
        size_bytes=len(data),
        s3_key=f"records/{world.patient.id}/{record_id}",
        is_hidden=hidden,
    )
    session.add(record)
    await session.flush()
    await storage.put_object(record.s3_key, data, content_type=content_type)
    return record


def _status(record: MedicalRecord) -> RecordProcessingStatus:
    """Read through a call so mypy does not narrow a field the service mutates."""
    return record.processing_status


async def _chunk_count(session: AsyncSession, record_id: UUID) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(AIChunk)
        .join(AIDocument, AIDocument.id == AIChunk.document_id)
        .where(AIDocument.record_id == record_id)
    )
    return int(result.scalar_one())


# -- outcomes -------------------------------------------------------------------------


def test_text_pdf_is_indexed_and_marked_indexed() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            world = await _setup_world(session)
            storage = FakeObjectStorage()
            record = await _add_record(session, world, storage, data=text_pdf(PDF_TEXT))

            result = await UploadIndexingService(session, storage).index_uploaded_record(
                record.id, final_attempt=False
            )

            assert result.outcome is IndexingOutcome.INDEXED
            assert result.chunk_count >= 1
            assert record.processing_status is RecordProcessingStatus.INDEXED
            chunks = (await session.execute(select(AIChunk))).scalars().all()
            assert {c.patient_id for c in chunks} == {world.patient.id}
            assert {c.category_id for c in chunks} == {world.cat_condition.id}
            assert any("Haemoglobin 9.8" in c.content for c in chunks)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("data", "content_type", "outcome", "status"),
    [
        (b"\x89PNG\r\n\x1a\nimage", "image/png", IndexingOutcome.UNSUPPORTED_TYPE, "UPLOADED"),
        (b"\xff\xd8\xffimage", "image/jpeg", IndexingOutcome.UNSUPPORTED_TYPE, "UPLOADED"),
        (blank_pdf(), "application/pdf", IndexingOutcome.NO_TEXT, "FAILED"),
        (encrypted_pdf(), "application/pdf", IndexingOutcome.ENCRYPTED, "FAILED"),
        (b"MZ not really a pdf", "application/pdf", IndexingOutcome.UNREADABLE, "FAILED"),
    ],
)
def test_unindexable_uploads_write_nothing_and_say_why(
    data: bytes, content_type: str, outcome: IndexingOutcome, status: str
) -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            world = await _setup_world(session)
            storage = FakeObjectStorage()
            record = await _add_record(
                session, world, storage, data=data, content_type=content_type
            )

            result = await UploadIndexingService(session, storage).index_uploaded_record(
                record.id, final_attempt=False
            )

            assert result.outcome is outcome
            assert record.processing_status.value == status
            assert await _chunk_count(session, record.id) == 0
            assert await AIRepository(session).get_document_by_record_id(record.id) is None

    asyncio.run(scenario())


def test_malformed_pdf_parser_exception_is_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    from pypdf import PdfReader

    async def scenario() -> None:
        async with sqlite_session() as session:
            world = await _setup_world(session)
            storage = FakeObjectStorage()
            record = await _add_record(
                session, world, storage, data=b"%PDF-corrupt", content_type="application/pdf"
            )

            def raise_corrupt(*args: Any, **kwargs: Any) -> None:
                raise IndexError("corrupted xref stream index out of range")

            monkeypatch.setattr(PdfReader, "__init__", raise_corrupt)
            result = await UploadIndexingService(session, storage).index_uploaded_record(
                record.id, final_attempt=False
            )

            assert result.outcome is IndexingOutcome.UNREADABLE
            assert record.processing_status is RecordProcessingStatus.FAILED
            assert await _chunk_count(session, record.id) == 0

    asyncio.run(scenario())


def test_missing_record_is_reported_not_raised() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            result = await UploadIndexingService(
                session, FakeObjectStorage()
            ).index_uploaded_record(uuid4(), final_attempt=False)
            assert result.outcome is IndexingOutcome.RECORD_NOT_FOUND

    asyncio.run(scenario())


# -- idempotency and retries ----------------------------------------------------------


def test_redelivery_never_duplicates_chunks() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            world = await _setup_world(session)
            storage = FakeObjectStorage()
            record = await _add_record(session, world, storage, data=text_pdf(PDF_TEXT))
            service = UploadIndexingService(session, storage)

            first = await service.index_uploaded_record(record.id, final_attempt=False)
            count = await _chunk_count(session, record.id)
            second = await service.index_uploaded_record(record.id, final_attempt=False)

            assert first.outcome is IndexingOutcome.INDEXED
            assert second.outcome is IndexingOutcome.ALREADY_INDEXED
            assert await _chunk_count(session, record.id) == count
            assert record.processing_status is RecordProcessingStatus.INDEXED

    asyncio.run(scenario())


def test_concurrent_delivery_that_loses_the_insert_race_is_already_indexed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both deliveries saw "not indexed"; the UNIQUE on ai_documents.record_id decides."""

    async def scenario() -> None:
        async with sqlite_session() as session:
            world = await _setup_world(session)
            storage = FakeObjectStorage()
            record = await _add_record(session, world, storage, data=text_pdf(PDF_TEXT))
            await UploadIndexingService(session, storage).index_uploaded_record(
                record.id, final_attempt=False
            )
            count = await _chunk_count(session, record.id)

            async def stale_lookup(self: AIRepository, record_id: UUID) -> None:
                return None  # the loser's view, read before the winner committed

            monkeypatch.setattr(AIRepository, "get_document_by_record_id", stale_lookup)
            result = await UploadIndexingService(session, storage).index_uploaded_record(
                record.id, final_attempt=False
            )

            assert result.outcome is IndexingOutcome.ALREADY_INDEXED
            monkeypatch.undo()
            assert await _chunk_count(session, record.id) == count

    asyncio.run(scenario())


def test_storage_outage_is_retried_and_only_the_final_attempt_fails() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            world = await _setup_world(session)
            storage = FakeObjectStorage()
            record = await _add_record(session, world, storage, data=text_pdf(PDF_TEXT))
            storage.storage_error = StorageUnavailableError()
            service = UploadIndexingService(session, storage)

            with pytest.raises(StorageUnavailableError):
                await service.index_uploaded_record(record.id, final_attempt=False)
            assert _status(record) is RecordProcessingStatus.UPLOADED

            final = await service.index_uploaded_record(record.id, final_attempt=True)
            assert final.outcome is IndexingOutcome.STORAGE_FAILED
            assert _status(record) is RecordProcessingStatus.FAILED

            # Storage back: a later delivery (e.g. a backfill) can still index it.
            storage.storage_error = None
            again = await service.index_uploaded_record(record.id, final_attempt=False)
            assert again.outcome is IndexingOutcome.INDEXED
            assert _status(record) is RecordProcessingStatus.INDEXED

    asyncio.run(scenario())


# -- the worker task ------------------------------------------------------------------


def _seed_world_in(engine: AsyncEngine, storage: FakeObjectStorage, data: bytes) -> UUID:
    async def run() -> UUID:
        factory = create_session_factory(engine)
        async with factory() as session, session.begin():
            world = await _setup_world(session)
            record = await _add_record(session, world, storage, data=data)
            return record.id

    return asyncio.run(run())


def test_worker_task_commits_the_index_and_logs_no_document_text(
    db_engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    storage = FakeObjectStorage()
    record_id = _seed_world_in(db_engine, storage, text_pdf(PDF_TEXT))
    ctx: dict[str, Any] = {
        "session_factory": create_session_factory(db_engine),
        "storage": storage,
        "job_try": 1,
    }

    # The worker's own logging setup at its most verbose: nothing it emits may carry text.
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    configure_logging("DEBUG")
    root.addHandler(caplog.handler)
    caplog.handler.setLevel(logging.DEBUG)
    try:
        outcome = asyncio.run(record_uploaded(ctx, record_id=str(record_id)))
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)

    assert outcome == "INDEXED"
    logged = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert SECRET_LINE not in logged and "Haemoglobin" not in logged
    assert str(record_id) in logged

    async def committed() -> tuple[RecordProcessingStatus, int]:
        factory = create_session_factory(db_engine)
        async with factory() as session:
            record = await session.get(MedicalRecord, record_id)
            assert record is not None
            return record.processing_status, await _chunk_count(session, record_id)

    status, count = asyncio.run(committed())
    assert status is RecordProcessingStatus.INDEXED
    assert count >= 1


def test_worker_task_retries_storage_outage_until_the_last_try(db_engine: AsyncEngine) -> None:
    storage = FakeObjectStorage()
    record_id = _seed_world_in(db_engine, storage, text_pdf(PDF_TEXT))
    storage.storage_error = StorageUnavailableError()
    factory = create_session_factory(db_engine)

    with pytest.raises(StorageUnavailableError):
        asyncio.run(
            record_uploaded(
                {"session_factory": factory, "storage": storage, "job_try": MAX_TRIES - 1},
                record_id=str(record_id),
            )
        )
    last = asyncio.run(
        record_uploaded(
            {"session_factory": factory, "storage": storage, "job_try": MAX_TRIES},
            record_id=str(record_id),
        )
    )
    assert last == "STORAGE_FAILED"


def test_worker_task_ignores_a_malformed_id(db_engine: AsyncEngine) -> None:
    ctx = {"session_factory": create_session_factory(db_engine), "storage": FakeObjectStorage()}
    assert asyncio.run(record_uploaded(ctx, record_id="not-a-uuid")) == "RECORD_NOT_FOUND"


# -- retrieval obeys consent, visibility and ownership --------------------------------


def test_indexed_pdf_text_is_searchable_only_within_consent_and_visibility() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            world = await _setup_world(session)
            storage = FakeObjectStorage()
            record = await _add_record(session, world, storage, data=text_pdf(PDF_TEXT))
            await UploadIndexingService(session, storage).index_uploaded_record(
                record.id, final_attempt=False
            )

            async def doctor_search() -> list[Any]:
                return await world.query_service.search_records(
                    world.doctor_auth, patient_id=world.patient.id, query="ferritin"
                )

            # Granted category: the uploaded PDF's text is retrievable.
            hits = await doctor_search()
            assert any(hit.record_id == record.id for hit in hits)

            # Hidden by the patient: gone for the clinician at once, no re-index needed.
            record.is_hidden = True
            await session.flush()
            assert not any(hit.record_id == record.id for hit in await doctor_search())
            record.is_hidden = False
            await session.flush()

            # Consent revoked: nothing.
            await world.consent_service.revoke_grant(world.patient_auth, world.grant_condition.id)
            assert await doctor_search() == []

    asyncio.run(scenario())


def test_indexed_pdf_in_an_ungranted_category_is_not_retrievable_by_the_clinician() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            world = await _setup_world(session)
            storage = FakeObjectStorage()
            # Revoke the observation grant, then file the PDF under that category.
            await world.consent_service.revoke_grant(world.patient_auth, world.grant_observation.id)
            record = await _add_record(
                session,
                world,
                storage,
                data=text_pdf(PDF_TEXT),
                category_id=world.cat_observation.id,
            )
            await UploadIndexingService(session, storage).index_uploaded_record(
                record.id, final_attempt=False
            )

            hits = await world.query_service.search_records(
                world.doctor_auth, patient_id=world.patient.id, query="ferritin"
            )
            assert not any(hit.record_id == record.id for hit in hits)

    asyncio.run(scenario())


def test_owner_retrieval_includes_own_hidden_pdf_and_no_other_patient_sees_it() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            world = await _setup_world(session)
            storage = FakeObjectStorage()
            record = await _add_record(
                session, world, storage, data=text_pdf(PDF_TEXT), hidden=True
            )
            await UploadIndexingService(session, storage).index_uploaded_record(
                record.id, final_attempt=False
            )
            ai = AIRepository(session)
            scope = frozenset({world.cat_condition.id, world.cat_observation.id})

            own = await ai.search_chunks(patient_id=world.patient.id, category_ids=scope)
            assert any(c.document_id for c in own)  # the owner sees their hidden upload
            other = await ai.search_chunks(patient_id=uuid4(), category_ids=scope)
            assert other == []

    asyncio.run(scenario())


def test_backfill_indexes_pending_pdfs_and_skips_images_and_indexed(db_engine: AsyncEngine) -> None:
    storage = FakeObjectStorage()

    async def arrange() -> tuple[UUID, UUID, UUID]:
        factory = create_session_factory(db_engine)
        async with factory() as session, session.begin():
            world = await _setup_world(session)
            pending = await _add_record(session, world, storage, data=text_pdf(PDF_TEXT))
            scan = await _add_record(session, world, storage, data=blank_pdf())
            image = await _add_record(
                session, world, storage, data=b"\x89PNG image", content_type="image/png"
            )
            return pending.id, scan.id, image.id

    pending_id, scan_id, image_id = asyncio.run(arrange())
    factory = create_session_factory(db_engine)

    first = asyncio.run(backfill_uploaded_records(factory, storage))
    second = asyncio.run(backfill_uploaded_records(factory, storage))

    assert first == {IndexingOutcome.INDEXED: 1, IndexingOutcome.NO_TEXT: 1}
    # The scan stays FAILED and is retried (still no text); the indexed PDF is not revisited.
    assert second == {IndexingOutcome.NO_TEXT: 1}

    async def statuses() -> dict[UUID, RecordProcessingStatus]:
        async with factory() as session:
            rows = await session.execute(select(MedicalRecord.id, MedicalRecord.processing_status))
            return dict(rows.tuples().all())

    by_id = asyncio.run(statuses())
    assert by_id[pending_id] is RecordProcessingStatus.INDEXED
    assert by_id[scan_id] is RecordProcessingStatus.FAILED
    assert by_id[image_id] is RecordProcessingStatus.UPLOADED
