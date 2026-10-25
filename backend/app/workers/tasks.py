"""Worker task functions (ADR-008/ADR-014). Same codebase as the API, separate process.

``record_uploaded`` indexes an uploaded record's text for local AI retrieval
(``records/upload_indexing.py``): text-layer PDFs only — no OCR, so images and scanned PDFs
are not indexed. One job is one database transaction. Only opaque IDs and outcome codes are
ever logged — no filenames, no patient identifiers, no document text (docs/SECURITY.md).

The worker's resources (session factory, object storage) are built once in
``app/workers/main.py`` startup and handed in through ``ctx``.
"""

import logging
from typing import Any, Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.records.storage import ObjectStorage
from app.modules.records.upload_indexing import UploadIndexingService

logger = logging.getLogger(__name__)

#: Attempts before a storage failure is recorded as FAILED rather than retried. Mirrors
#: ``WorkerSettings.max_tries`` (kept here so tests need not import the Redis settings).
MAX_TRIES: Final = 5


async def record_uploaded(ctx: dict[str, Any], *, record_id: str) -> str:
    """Index one uploaded record; returns the outcome code (also arq's job result)."""
    session_factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    storage: ObjectStorage = ctx["storage"]
    final_attempt = int(ctx.get("job_try", 1)) >= MAX_TRIES
    try:
        parsed = UUID(str(record_id))
    except (ValueError, TypeError, AttributeError):
        logger.warning("record_uploaded ignored: malformed record id")
        return "RECORD_NOT_FOUND"
    async with session_factory() as session, session.begin():
        result = await UploadIndexingService(session, storage).index_uploaded_record(
            parsed, final_attempt=final_attempt
        )
    logger.info(
        "record_uploaded processed",
        extra={
            "record_id": record_id,
            "outcome": result.outcome.value,
            "chunks": result.chunk_count,
        },
    )
    return result.outcome.value
