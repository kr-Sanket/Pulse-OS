"""AI ingestion orchestration from sanitized FHIR resources."""

from __future__ import annotations

import json
from collections.abc import Mapping
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
        resource: Mapping[str, Any] | bytes | str,
        source_version: int = 1,
        max_tokens: int = 120,
        reindex: bool = False,
    ) -> AIDocument | None:
        """Normalize and index one sanitized FHIR resource."""
        if isinstance(resource, (bytes, bytearray, str)):
            resource_dict: Mapping[str, Any] = json.loads(resource)
        else:
            resource_dict = resource

        normalized_text = normalize_fhir_resource(resource_dict)

        if not normalized_text:
            return None

        return await self._service.index_record(
            record_id=record_id,
            patient_id=patient_id,
            category_id=category_id,
            normalized_text=normalized_text,
            source_version=source_version,
            max_tokens=max_tokens,
            reindex=reindex,
        )
