"""AI/RAG document ingestion orchestration."""

from __future__ import annotations

from uuid import UUID

from app.modules.ai.chunking import build_document_payload
from app.modules.ai.models import AIDocument, AIChunk
from app.modules.ai.repository import AIRepository
from .retrieval import RetrievedChunk, lexical_score, normalize_query

from typing import Protocol

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

class RetrievalScope(Protocol):
    """Provides the caller's currently authorized category scope."""

    async def granted_category_ids(
        self,
        requester,
        *,
        patient_id: UUID,
        at,
    ) -> frozenset[UUID]:
        ...

class AIRetrievalService:
    """Deterministic retrieval over consent-scoped AI chunks."""

    def __init__(self, repository: AIRepository) -> None:
        self._repository = repository

    async def search(
        self,
        *,
        patient_id: UUID,
        category_ids: frozenset[UUID],
        query: str,
        limit: int = 10,
    ) -> list[RetrievedChunk]:
        """Search only within the categories already authorized."""
        if limit <= 0:
            return []

        chunks = await self._repository.search_chunks(
            patient_id=patient_id,
            category_ids=category_ids,
        )

        if not chunks:
            return []

        query_terms = normalize_query(query)

        if not query_terms:
            return []

        document_ids = {chunk.document_id for chunk in chunks}
        documents = {}

        for document_id in document_ids:
            document = await self._repository.get_document_by_id(document_id)
            if document is not None:
                documents[document_id] = document

        ranked: list[RetrievedChunk] = []

        for chunk in chunks:
            score = lexical_score(chunk.content, query_terms)

            if score == 0:
                continue

            document = documents.get(chunk.document_id)

            if document is None:
                continue

            ranked.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    record_id=document.record_id,
                    patient_id=chunk.patient_id,
                    category_id=chunk.category_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                    token_count=chunk.token_count,
                    score=score,
                )
            )

        ranked.sort(
            key=lambda item: (
                -item.score,
                str(item.document_id),
                item.chunk_index,
                str(item.chunk_id),
            )
        )

        return ranked[:limit]