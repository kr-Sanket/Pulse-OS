"""Persistence for AI/RAG-owned tables.

Pure persistence only — no normalization, chunking, authorization, or
transaction commits. The caller owns the transaction boundary.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.models import AIDocument, AIChunk


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
