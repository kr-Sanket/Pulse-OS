"""Provider-agnostic clinical answer generation abstractions and test fakes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.modules.ai.context import AssembledContext


@dataclass(frozen=True)
class CitationReference:
    """Application-side provenance mapping linking a cited evidence chunk to a source record."""

    citation_index: int
    record_id: UUID
    category_code: str
    chunk_index: int


@dataclass(frozen=True)
class GeneratedAnswer:
    """Provider-independent domain result for generated clinical answers."""

    answer: str
    citations: tuple[CitationReference, ...]
    provider: str
    model: str
    generated_at: datetime


@runtime_checkable
class AnswerGenerator(Protocol):
    """Provider-agnostic interface for clinical answer synthesis."""

    async def generate_answer(
        self,
        context: AssembledContext,
    ) -> GeneratedAnswer:
        """Synthesize an answer and citations deterministically from assembled context."""
        ...


class FakeAnswerGenerator:
    """Deterministic, network-free AnswerGenerator for tests and local development."""

    def __init__(
        self,
        answer_template: str = "Based on the available evidence [1].",
    ) -> None:
        self.answer_template = answer_template
        self.calls: list[AssembledContext] = []

    async def generate_answer(
        self,
        context: AssembledContext,
    ) -> GeneratedAnswer:
        self.calls.append(context)

        return GeneratedAnswer(
            answer=self.answer_template,
            citations=tuple(
                CitationReference(
                    citation_index=item.citation_index,
                    record_id=item.record_id,
                    category_code=item.category_code,
                    chunk_index=item.chunk_index,
                )
                for item in context.items
            ),
            provider="fake",
            model="fake-v1",
            generated_at=datetime.now(UTC),
        )
