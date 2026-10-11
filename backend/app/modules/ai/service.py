"""AI/RAG document ingestion orchestration."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import date
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from app.modules.ai.chunking import build_document_payload
from app.modules.ai.models import AIChunk, AIDocument

from .retrieval import (
    RetrievedChunk,
    lexical_score,
    normalize_query,
    rank_retrieved_chunks,
)


class IngestionRepository(Protocol):
    """The persistence ``AIIngestionService`` uses — implemented by ``AIRepository``."""

    async def get_document_by_record_id(self, record_id: UUID) -> AIDocument | None: ...

    async def add_document(self, document: AIDocument) -> AIDocument: ...

    async def add_chunks(self, chunks: list[AIChunk]) -> list[AIChunk]: ...

    async def delete_chunks_by_document_id(self, document_id: UUID) -> None: ...


class RetrievalRepository(Protocol):
    """The persistence ``AIRetrievalService`` uses — implemented by ``AIRepository``.

    Both chunk queries are required: the caller's ``RetrievalVisibility`` picks one, so an
    implementation cannot offer the owner query without the grantee one.
    """

    async def search_chunks(
        self, *, patient_id: UUID, category_ids: frozenset[UUID]
    ) -> list[AIChunk]: ...

    async def search_grantee_chunks(
        self, *, patient_id: UUID, category_ids: frozenset[UUID]
    ) -> list[AIChunk]: ...

    async def get_document_by_id(self, document_id: UUID) -> AIDocument | None: ...


class AIIngestionService:
    """Build and persist deterministic AI representations of medical records."""

    def __init__(self, repository: IngestionRepository) -> None:
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


class RetrievalVisibility(StrEnum):
    """Which records a retrieval may draw on — chosen by the caller, never defaulted.

    ``GRANTEE``: a consented clinician; records the patient has hidden are excluded.
    ``OWNER``: the patient querying their own records; hidden records stay included, as they
    do in every other owner surface (docs/DOMAIN_MODEL.md §3).
    """

    GRANTEE = "GRANTEE"
    OWNER = "OWNER"


class AIRetrievalService:
    """Deterministic retrieval over consent-scoped AI chunks."""

    def __init__(
        self,
        repository: RetrievalRepository,
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
        visibility: RetrievalVisibility,
        limit: int = 10,
    ) -> list[RetrievedChunk]:
        """Search only within the categories already authorized.

        ``visibility`` is required: a default would silently pick one party's policy for
        the other. The hidden-record filter runs in the query, before scoring and ``limit``.
        """
        if limit <= 0:
            return []

        if visibility is RetrievalVisibility.GRANTEE:
            chunks = await self._repository.search_grantee_chunks(
                patient_id=patient_id,
                category_ids=category_ids,
            )
        elif visibility is RetrievalVisibility.OWNER:
            chunks = await self._repository.search_chunks(
                patient_id=patient_id,
                category_ids=category_ids,
            )
        else:
            raise ValueError(f"unsupported retrieval visibility: {visibility!r}")

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
