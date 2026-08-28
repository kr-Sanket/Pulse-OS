"""Worker task functions (ADR-008/ADR-014). Same codebase as the API, separate process.

M2 delivers the *skeleton*: the upload event is consumed and acknowledged, nothing more.
The M5 AI milestone replaces the body of ``record_uploaded`` with the OCR → chunk → embed
pipeline (docs/AI_ARCHITECTURE.md) and starts advancing ``processing_status``. Only opaque
IDs are ever logged — no filenames, no patient identifiers (docs/SECURITY.md).
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def record_uploaded(ctx: dict[str, Any], *, record_id: str) -> None:
    """Handle one uploaded record. M2: acknowledge only (the record stays UPLOADED)."""
    logger.info("record_uploaded received", extra={"record_id": record_id})
