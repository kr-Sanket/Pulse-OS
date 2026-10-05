"""Deterministic AI chunk retrieval primitives."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.modules.ai.models import AIChunk


@dataclass(frozen=True)
class RetrievedChunk:
    """One chunk returned by deterministic AI retrieval."""

    chunk_id: UUID
    document_id: UUID
    record_id: UUID
    patient_id: UUID
    category_id: UUID
    chunk_index: int
    content: str
    content_hash: str
    token_count: int
    score: int


def normalize_query(query: str) -> tuple[str, ...]:
    """Normalize a search query into deterministic unique terms."""
    return tuple(dict.fromkeys(query.lower().split()))


def lexical_score(content: str, query_terms: tuple[str, ...]) -> int:
    """Score content by the number of query terms it contains."""
    if not query_terms:
        return 0

    normalized_content = content.lower()
    return sum(term in normalized_content for term in query_terms)

def rank_chunks(
    chunks: list[AIChunk],
    query: str,
    *,
    limit: int = 10,
) -> list[RetrievedChunk]:
    """Rank candidate chunks deterministically using lexical matching."""
    if limit <= 0:
        return []

    query_terms = normalize_query(query)

    ranked: list[RetrievedChunk] = []

    for chunk in chunks:
        score = lexical_score(chunk.content, query_terms)

        if score == 0:
            continue

        ranked.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                record_id=chunk.document_id,
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