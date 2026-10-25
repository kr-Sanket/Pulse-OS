"""Index an uploaded record's text for local AI retrieval (ADR-008/ADR-014, M5 slice).

Runs in the arq worker after ``POST /records`` enqueues ``record_uploaded``. One call is one
transaction (the caller commits): read the record, fetch its object, extract text, write the
AI document and chunks, move ``processing_status``.

**What this does not decide — and must not.** Who may read the extracted text. Chunks carry
the record's ``patient_id`` and ``category_id`` and are read only through the existing
retrieval paths: a clinician's (``AIRepository.search_grantee_chunks``) is limited to the
currently granted categories and joins ``medical_records`` live to exclude hidden records; the
owner's (``search_chunks``) is limited to the patient themselves. The clinician answer path
re-checks consent after generation. Hiding a record after it is indexed therefore takes effect
on the next query without re-indexing.

Outcomes and status (``RecordProcessingStatus``):

* text-layer PDF → chunks written, ``INDEXED``;
* unsupported type (JPEG/PNG — no OCR) → nothing written, status stays ``UPLOADED``;
* PDF with no text / encrypted / unparseable → ``FAILED``; deterministic, so not retried;
* storage unavailable → raised so the worker retries; on the final attempt, ``FAILED``;
* already indexed (re-delivery, or a concurrent worker won) → nothing written.

No PHI is logged here or returned: outcomes are enum codes.
"""

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.ai.repository import AIRepository
from app.modules.ai.service import AIIngestionService
from app.modules.records.errors import StorageUnavailableError
from app.modules.records.models import MedicalRecord, RecordProcessingStatus
from app.modules.records.storage import ObjectStorage
from app.modules.records.text_extraction import (
    INDEXABLE_CONTENT_TYPES,
    ExtractionError,
    ExtractionFailure,
    extract_pdf_text,
    is_indexable,
)


class IndexingOutcome(StrEnum):
    INDEXED = "INDEXED"
    ALREADY_INDEXED = "ALREADY_INDEXED"
    UNSUPPORTED_TYPE = "UNSUPPORTED_TYPE"
    NO_TEXT = "NO_TEXT"
    ENCRYPTED = "ENCRYPTED"
    UNREADABLE = "UNREADABLE"
    STORAGE_FAILED = "STORAGE_FAILED"
    RECORD_NOT_FOUND = "RECORD_NOT_FOUND"


_FAILURE_OUTCOME = {
    ExtractionFailure.NO_TEXT: IndexingOutcome.NO_TEXT,
    ExtractionFailure.ENCRYPTED: IndexingOutcome.ENCRYPTED,
    ExtractionFailure.UNREADABLE: IndexingOutcome.UNREADABLE,
}


@dataclass(frozen=True, slots=True)
class IndexingResult:
    outcome: IndexingOutcome
    chunk_count: int = 0


class UploadIndexingService:
    """Turns one uploaded record into AI chunks, or records why it cannot be."""

    def __init__(self, session: AsyncSession, storage: ObjectStorage) -> None:
        self._session = session
        self._storage = storage
        self._ai = AIRepository(session)

    async def index_uploaded_record(
        self, record_id: UUID, *, final_attempt: bool
    ) -> IndexingResult:
        """Index one record. Raises ``StorageUnavailableError`` only when a retry may help."""
        record = await self._session.get(MedicalRecord, record_id)
        if record is None:
            return IndexingResult(IndexingOutcome.RECORD_NOT_FOUND)
        if not is_indexable(record.content_type):
            return IndexingResult(IndexingOutcome.UNSUPPORTED_TYPE)
        if await self._ai.get_document_by_record_id(record.id) is not None:
            record.processing_status = RecordProcessingStatus.INDEXED
            await self._session.flush()
            return IndexingResult(IndexingOutcome.ALREADY_INDEXED)

        try:
            data = await self._storage.get_object(record.s3_key)
        except StorageUnavailableError:
            if not final_attempt:
                raise
            return await self._fail(record, IndexingOutcome.STORAGE_FAILED)

        try:
            text = await asyncio.to_thread(extract_pdf_text, data)
        except ExtractionError as exc:
            return await self._fail(record, _FAILURE_OUTCOME[exc.reason])

        try:
            async with self._session.begin_nested():
                document = await AIIngestionService(self._ai).index_record(
                    record_id=record.id,
                    patient_id=record.patient_id,
                    category_id=record.category_id,
                    normalized_text=text,
                )
        except IntegrityError:
            # A concurrent delivery indexed it first (UNIQUE ai_documents.record_id).
            record.processing_status = RecordProcessingStatus.INDEXED
            await self._session.flush()
            return IndexingResult(IndexingOutcome.ALREADY_INDEXED)
        if document is None:
            record.processing_status = RecordProcessingStatus.INDEXED
            await self._session.flush()
            return IndexingResult(IndexingOutcome.ALREADY_INDEXED)

        record.processing_status = RecordProcessingStatus.INDEXED
        await self._session.flush()
        chunks = await self._ai.count_chunks_for_document(document.id)
        return IndexingResult(IndexingOutcome.INDEXED, chunk_count=chunks)

    async def _fail(self, record: MedicalRecord, outcome: IndexingOutcome) -> IndexingResult:
        record.processing_status = RecordProcessingStatus.FAILED
        await self._session.flush()
        return IndexingResult(outcome)


async def backfill_uploaded_records(
    session_factory: async_sessionmaker[AsyncSession],
    storage: ObjectStorage,
    *,
    limit: int | None = None,
) -> dict[IndexingOutcome, int]:
    """Index every not-yet-indexed uploaded PDF, one transaction per record.

    For uploads stored before the worker indexed them, or whose job exhausted its retries.
    Each record is processed as a final attempt (a storage outage records FAILED and the run
    continues). Returns counts per outcome — ids and codes only, never content.
    """
    async with session_factory() as session:
        query = (
            select(MedicalRecord.id)
            .where(
                MedicalRecord.content_type.in_(INDEXABLE_CONTENT_TYPES),
                MedicalRecord.processing_status != RecordProcessingStatus.INDEXED,
            )
            .order_by(MedicalRecord.id)
        )
        if limit is not None:
            query = query.limit(limit)
        record_ids = list((await session.execute(query)).scalars())

    counts: dict[IndexingOutcome, int] = {}
    for record_id in record_ids:
        async with session_factory() as session, session.begin():
            result = await UploadIndexingService(session, storage).index_uploaded_record(
                record_id, final_attempt=True
            )
        counts[result.outcome] = counts.get(result.outcome, 0) + 1
    return counts
