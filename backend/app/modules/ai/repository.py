"""Persistence for AI/RAG-owned tables.

Pure persistence only — no normalization, chunking, authorization, or
transaction commits. The caller owns the transaction boundary.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.models import AIChunk, AIDocument
from app.modules.records.models import MedicalRecord


class AIRepository:
    """Persistence operations for AI documents and chunks."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_document_by_record_id(
        self,
        record_id: UUID,
    ) -> AIDocument | None:
        """Return the AI document for a medical record, if indexed."""
        result = await self._session.execute(
            select(AIDocument).where(AIDocument.record_id == record_id)
        )
        return result.scalar_one_or_none()

    async def add_document(
        self,
        document: AIDocument,
    ) -> AIDocument:
        """Persist and flush an AI document."""
        self._session.add(document)
        await self._session.flush()
        return document

    async def add_chunks(
        self,
        chunks: list[AIChunk],
    ) -> list[AIChunk]:
        """Persist and flush AI chunks."""
        if not chunks:
            return []

        self._session.add_all(chunks)
        await self._session.flush()
        return chunks

    async def search_chunks(
        self,
        *,
        patient_id: UUID,
        category_ids: frozenset[UUID],
    ) -> list[AIChunk]:
        """Return AI chunks within the caller's already-authorized scope."""
        if not category_ids:
            return []

        stmt = (
            select(AIChunk)
            .where(
                AIChunk.patient_id == patient_id,
                AIChunk.category_id.in_(category_ids),
            )
            .order_by(
                AIChunk.document_id,
                AIChunk.chunk_index,
                AIChunk.id,
            )
        )

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def search_grantee_chunks(
        self,
        *,
        patient_id: UUID,
        category_ids: frozenset[UUID],
    ) -> list[AIChunk]:
        """Return AI chunks a consented clinician may retrieve: scoped *and* visible.

        The AI counterpart of ``RecordRepository.list_page_for_grantee``. Chunks of a record
        the patient has hidden are excluded unconditionally, in the query, so they never reach
        scoring, the retrieval limit, generation context, or citations (docs/DOMAIN_MODEL.md
        §3). Visibility is read live from ``medical_records`` rather than copied into the AI
        tables, so hiding or unhiding takes effect without re-indexing.

        Separate from ``search_chunks`` rather than a flag on it: the owner path must keep
        hidden records and the grantee path must never see them, and an argument reconciling
        the two would have to default to one of them.
        """
        if not category_ids:
            return []

        stmt = (
            select(AIChunk)
            .join(AIDocument, AIDocument.id == AIChunk.document_id)
            .join(MedicalRecord, MedicalRecord.id == AIDocument.record_id)
            .where(
                AIChunk.patient_id == patient_id,
                AIChunk.category_id.in_(category_ids),
                MedicalRecord.is_hidden.is_(False),
            )
            .order_by(
                AIChunk.document_id,
                AIChunk.chunk_index,
                AIChunk.id,
            )
        )

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_document_by_id(
        self,
        document_id: UUID,
    ) -> AIDocument | None:
        result = await self._session.execute(select(AIDocument).where(AIDocument.id == document_id))
        return result.scalar_one_or_none()

    async def delete_chunks_by_document_id(
        self,
        document_id: UUID,
    ) -> None:
        """Delete all chunks for a document."""
        await self._session.execute(delete(AIChunk).where(AIChunk.document_id == document_id))
        await self._session.flush()
