"""AI/RAG document ingestion orchestration."""

from __future__ import annotations

from uuid import UUID

from app.modules.ai.chunking import build_document_payload
from app.modules.ai.models import AIDocument, AIChunk
from app.modules.ai.repository import AIRepository


class AIIngestionService:
    """Build and persist deterministic AI representations of medical records."""

    def __init__(self, repository: AIRepository) -> None:
        self._repository = repository

    async def index_record(
        self,
        *,
        record_id: UUID,
        patient_id: UUID,
        category_id: UUID,
        normalized_text: str,
        source_version: int = 1,
        max_tokens: int = 120,
    ) -> AIDocument | None:
        """Index one medical record if it has not already been indexed.

        Returns the newly created document, or None when the record was
        already indexed.

        The caller owns the transaction and commit boundary.
        """
        existing = await self._repository.get_document_by_record_id(record_id)

        if existing is not None:
            return None

        payload = build_document_payload(
            normalized_text,
            source_version=source_version,
            max_tokens=max_tokens,
        )

        document = AIDocument(
            record_id=record_id,
            patient_id=patient_id,
            category_id=category_id,
            content_hash=payload.content_hash,
            source_version=payload.source_version,
        )

        await self._repository.add_document(document)

        chunks = [
            AIChunk(
                document_id=document.id,
                patient_id=patient_id,
                category_id=category_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                content_hash=chunk.content_hash,
                token_count=chunk.token_count,
            )
            for chunk in payload.chunks
        ]

        await self._repository.add_chunks(chunks)

        return document