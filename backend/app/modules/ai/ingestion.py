"""AI ingestion orchestration from sanitized FHIR resources."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.modules.ai.models import AIDocument
from app.modules.ai.service import AIIngestionService
from app.modules.ai.text import normalize_fhir_resource


class AIRecordIngestion:
    """Convert sanitized FHIR resources into persisted AI representations."""

    def __init__(self, service: AIIngestionService) -> None:
        self._service = service

    async def index_fhir_resource(
        self,
        *,
        record_id: UUID,
        patient_id: UUID,
        category_id: UUID,
        resource: dict[str, Any],
        source_version: int = 1,
        max_tokens: int = 120,
    ) -> AIDocument | None:
        """Normalize and index one sanitized FHIR resource."""
        normalized_text = normalize_fhir_resource(resource)

        if not normalized_text:
            return None

        return await self._service.index_record(
            record_id=record_id,
            patient_id=patient_id,
            category_id=category_id,
            normalized_text=normalized_text,
            source_version=source_version,
            max_tokens=max_tokens,
        )