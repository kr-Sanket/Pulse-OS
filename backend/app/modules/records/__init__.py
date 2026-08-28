"""Records module: clinical document metadata, categorization, and processing lifecycle."""

from app.modules.records.models import (
    DEFAULT_RECORD_CATEGORIES,
    MedicalRecord,
    ProcessingStatus,
    RecordCategory,
    RecordOrigin,
)
from app.modules.records.service import RecordService

__all__ = [
    "DEFAULT_RECORD_CATEGORIES",
    "MedicalRecord",
    "ProcessingStatus",
    "RecordCategory",
    "RecordOrigin",
    "RecordService",
]
