from collections.abc import Mapping
from datetime import datetime, timezone
from uuid import UUID

from app.modules.auth.domain import AuthenticatedUser

from .context import AssembledContext, assemble_context
from .retrieval import RetrievedChunk
from .service import AIRetrievalService, RetrievalScope


class AIQueryService:
    """Coordinates consent scope and deterministic AI retrieval."""

    def __init__(
        self,
        retrieval: AIRetrievalService,
        consent: RetrievalScope,
    ) -> None:
        self._retrieval = retrieval
        self._consent = consent

    async def search(
        self,
        requester: AuthenticatedUser,
        *,
        patient_id: UUID,
        query: str,
        limit: int = 10,
    ) -> list[RetrievedChunk]:
        category_ids = await self._consent.granted_category_ids(
            requester,
            patient_id=patient_id,
            at=datetime.now(timezone.utc),
        )

        return await self._retrieval.search(
            patient_id=patient_id,
            category_ids=category_ids,
            query=query,
            limit=limit,
        )

    async def assemble_context(
        self,
        requester: AuthenticatedUser,
        *,
        patient_id: UUID,
        query: str,
        category_codes: Mapping[UUID, str],
        limit: int = 10,
        max_tokens: int = 1000,
    ) -> AssembledContext:
        chunks = await self.search(
            requester,
            patient_id=patient_id,
            query=query,
            limit=limit,
        )

        return assemble_context(
            query=query,
            patient_id=patient_id,
            chunks=chunks,
            category_codes=category_codes,
            max_tokens=max_tokens,
        )