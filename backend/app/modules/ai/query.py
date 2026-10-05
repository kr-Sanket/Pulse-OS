from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Final, Protocol
from uuid import UUID

from app.modules.auth.domain import AuthenticatedUser

from .context import AssembledContext, assemble_context
from .generation import AnswerGenerator, GeneratedAnswer
from .retrieval import RetrievedChunk
from .service import AIRetrievalService, RetrievalScope

DEFAULT_EMPTY_EVIDENCE_ANSWER: Final[str] = (
    "The available medical records do not contain information regarding the requested topic."
)


class SummaryAuditor(Protocol):
    """How AI summary generation reaches the patient's audit trail."""

    async def record_summary_generated(
        self,
        requester: AuthenticatedUser,
        *,
        patient_id: UUID,
        at: datetime,
        request_context: str | None = None,
    ) -> None: ...


class AIQueryService:
    """Coordinates consent scope, deterministic AI retrieval, and answer synthesis."""

    def __init__(
        self,
        retrieval: AIRetrievalService,
        consent: RetrievalScope,
        auditor: SummaryAuditor | None = None,
    ) -> None:
        self._retrieval = retrieval
        self._consent = consent
        self._auditor = auditor if auditor is not None else (
            consent if hasattr(consent, "record_summary_generated") else None
        )

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

    async def generate_answer(
        self,
        requester: AuthenticatedUser,
        *,
        patient_id: UUID,
        query: str,
        category_codes: Mapping[UUID, str],
        generator: AnswerGenerator,
        limit: int = 10,
        max_tokens: int = 1000,
        request_context: str | None = None,
    ) -> GeneratedAnswer:
        """Coordinate retrieval, context assembly, and answer synthesis with audit recording.

        1. Resolves consent-authorized categories and retrieves matching chunks.
        2. Deterministically assembles context adhering to token budget.
        3. If context contains no evidence:
           - Bypasses AnswerGenerator (neither Gemini nor Fake is called).
           - Bypasses audit recording (no summary was synthesized).
           - Returns deterministic empty-evidence GeneratedAnswer immediately.
        4. If context contains evidence:
           - Invokes the injected AnswerGenerator.
           - Only AFTER successful generation, records SUMMARY_GENERATED audit event.
           - Returns the GeneratedAnswer.
        """
        context = await self.assemble_context(
            requester,
            patient_id=patient_id,
            query=query,
            category_codes=category_codes,
            limit=limit,
            max_tokens=max_tokens,
        )

        now = datetime.now(timezone.utc)

        # Empty-context check: do NOT call generator, do NOT write audit
        if not context.items:
            provider = getattr(generator, "provider", "fake" if "Fake" in type(generator).__name__ else "gemini")
            model = getattr(generator, "model", "fake-v1" if "Fake" in type(generator).__name__ else "gemini-3.8-flash")
            return GeneratedAnswer(
                answer=DEFAULT_EMPTY_EVIDENCE_ANSWER,
                citations=(),
                provider=str(provider),
                model=str(model),
                generated_at=now,
            )

        # Context has evidence: invoke generator
        generated = await generator.generate_answer(context)

        # Audit recording: only after successful generation
        if self._auditor is not None:
            await self._auditor.record_summary_generated(
                requester,
                patient_id=patient_id,
                at=generated.generated_at,
                request_context=request_context,
            )

        return generated