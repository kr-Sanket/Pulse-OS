"""AI/RAG document ingestion orchestration."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import date
from typing import Any, Protocol
from uuid import UUID

from app.modules.ai.chunking import build_document_payload
from app.modules.ai.models import AIChunk, AIDocument
from app.modules.ai.repository import AIRepository

from .retrieval import (
    RetrievedChunk,
    lexical_score,
    normalize_query,
    rank_retrieved_chunks,
)


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
        reindex: bool = False,
    ) -> AIDocument | None:
        """Index one medical record if it has not already been indexed.

        Returns the created or updated document, or None when the record was
        already indexed (or unchanged under reindex).

        The caller owns the transaction and commit boundary.
        """
        existing = await self._repository.get_document_by_record_id(record_id)

        if existing is not None and not reindex:
            return None

        payload = build_document_payload(
            normalized_text,
            source_version=source_version,
            max_tokens=max_tokens,
        )

        if existing is not None:
            if existing.content_hash == payload.content_hash:
                return None

            existing.content_hash = payload.content_hash
            existing.source_version = payload.source_version
            await self._repository.delete_chunks_by_document_id(existing.id)

            chunks = [
                AIChunk(
                    document_id=existing.id,
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

            return existing

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
        requester: Any,
        *,
        patient_id: UUID,
        at: Any,
    ) -> frozenset[UUID]: ...


class RecordDateLookup(Protocol):
    """Provides clinical dates of service for medical records."""

    async def dates_by_record_ids(
        self,
        record_ids: Collection[UUID],
    ) -> Mapping[UUID, date]: ...


class AIRetrievalService:
    """Deterministic retrieval over consent-scoped AI chunks."""

    def __init__(
        self,
        repository: AIRepository,
        date_lookup: RecordDateLookup | None = None,
    ) -> None:
        self._repository = repository
        self._date_lookup = date_lookup
        if self._date_lookup is None and hasattr(repository, "_session"):
            session = repository._session
            if session is not None:
                from app.modules.records.directory import record_date_directory

                self._date_lookup = record_date_directory(session)

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

        # Collect unique record IDs to query dates in a single batched lookup
        record_ids = {doc.record_id for doc in documents.values() if doc is not None}
        dates: Mapping[UUID, date] = {}
        if self._date_lookup is not None and record_ids:
            dates = await self._date_lookup.dates_by_record_ids(record_ids)

        ranked: list[RetrievedChunk] = []

        for chunk in chunks:
            score = lexical_score(chunk.content, query_terms)

            if score == 0:
                continue

            document = documents.get(chunk.document_id)

            if document is None:
                continue

            date_val = dates.get(document.record_id)

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
                    date_of_service=date_val,
                )
            )

        return rank_retrieved_chunks(ranked, query, limit=limit)
