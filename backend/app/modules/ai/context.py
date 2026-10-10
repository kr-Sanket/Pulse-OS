"""Deterministic AI context assembly primitives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID

from app.modules.ai.retrieval import RetrievedChunk


class ContextAudience(StrEnum):
    """The intended recipient role of the synthesized clinical context."""

    CLINICIAN = "CLINICIAN"
    PATIENT = "PATIENT"


@dataclass(frozen=True)
class ContextEvidenceItem:
    """One ordered evidence chunk within the assembled context package."""

    chunk_id: UUID
    record_id: UUID
    category_code: str
    chunk_index: int
    content: str
    token_count: int
    citation_index: int

    def __init__(
        self,
        chunk_id: UUID,
        record_id: UUID,
        category_code: str,
        chunk_index: int,
        content: str,
        token_count: int,
        citation_index: int,
        date_of_service: date | None = None,
    ) -> None:
        object.__setattr__(self, "chunk_id", chunk_id)
        object.__setattr__(self, "record_id", record_id)
        object.__setattr__(self, "category_code", category_code)
        object.__setattr__(self, "chunk_index", chunk_index)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "token_count", token_count)
        object.__setattr__(self, "citation_index", citation_index)
        object.__setattr__(self, "_date_of_service", date_of_service)

    @property
    def date_of_service(self) -> date | None:
        return getattr(self, "_date_of_service", None)


@dataclass(frozen=True)
class AssembledContext:
    """Deterministic, auditable context package ready for downstream consumption."""

    query: str
    patient_id: UUID
    items: tuple[ContextEvidenceItem, ...]
    total_tokens: int
    max_tokens: int
    is_truncated: bool
    dropped_chunk_count: int
    audience: ContextAudience = ContextAudience.CLINICIAN


def assemble_context(
    query: str,
    patient_id: UUID,
    chunks: list[RetrievedChunk],
    category_codes: Mapping[UUID, str],
    *,
    max_tokens: int = 1000,
    audience: ContextAudience = ContextAudience.CLINICIAN,
) -> AssembledContext:
    """Assemble a deterministic context package from retrieved chunks and budget.

    Preserves retrieval input order, maps category codes without external I/O,
    enforces a hard token budget atomically without partial-chunk splitting,
    and assigns 1-based sequential citation indexes.
    """
    if max_tokens <= 0:
        raise ValueError("max_tokens must be greater than zero")

    items: list[ContextEvidenceItem] = []
    total_tokens = 0
    is_truncated = False
    dropped_chunk_count = 0

    for idx, chunk in enumerate(chunks):
        if total_tokens + chunk.token_count <= max_tokens:
            category_code = category_codes[chunk.category_id]
            items.append(
                ContextEvidenceItem(
                    chunk_id=chunk.chunk_id,
                    record_id=chunk.record_id,
                    category_code=category_code,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    citation_index=len(items) + 1,
                    date_of_service=chunk.date_of_service,
                )
            )
            total_tokens += chunk.token_count
        else:
            is_truncated = True
            dropped_chunk_count = len(chunks) - idx
            break

    return AssembledContext(
        query=query,
        patient_id=patient_id,
        items=tuple(items),
        total_tokens=total_tokens,
        max_tokens=max_tokens,
        is_truncated=is_truncated,
        dropped_chunk_count=dropped_chunk_count,
        audience=audience,
    )
