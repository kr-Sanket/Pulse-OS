"""Deterministic AI chunk retrieval primitives."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final
from uuid import UUID

from app.modules.ai.models import AIChunk

CLINICAL_SYNONYMS: Final[dict[str, tuple[str, ...]]] = {
    # Vaccination / Immunization
    "vaccination": ("vaccine", "immunization"),
    "vaccinations": ("vaccine", "immunization"),
    "vaccinated": ("vaccine", "immunization"),
    "vaccine": ("vaccine", "immunization"),
    "vaccines": ("vaccine", "immunization"),
    "immunization": ("vaccine", "immunization"),
    "immunizations": ("vaccine", "immunization"),
    "immunisation": ("vaccine", "immunization"),
    # Lab / Diagnostics
    "lab": ("diagnosticreport", "panel", "observation", "report", "lab"),
    "labs": ("diagnosticreport", "panel", "observation", "report", "lab"),
    "laboratory": ("diagnosticreport", "panel", "observation", "report", "lab"),
    "report": ("diagnosticreport", "panel", "observation", "report", "lab"),
    "reports": ("diagnosticreport", "panel", "observation", "report", "lab"),
    # Medications
    "medication": ("medicationrequest", "medication", "prescription"),
    "medications": ("medicationrequest", "medication", "prescription"),
    "medicine": ("medicationrequest", "medication", "prescription"),
    "medicines": ("medicationrequest", "medication", "prescription"),
    "drug": ("medicationrequest", "medication", "prescription"),
    "drugs": ("medicationrequest", "medication", "prescription"),
    "prescription": ("medicationrequest", "medication", "prescription"),
    "prescriptions": ("medicationrequest", "medication", "prescription"),
    # Conditions
    "condition": ("condition", "finding", "disorder"),
    "conditions": ("condition", "finding", "disorder"),
    "illness": ("condition", "finding", "disorder"),
    "illnesses": ("condition", "finding", "disorder"),
    "disease": ("condition", "finding", "disorder"),
    "diseases": ("condition", "finding", "disorder"),
    "diagnosis": ("condition", "finding", "disorder"),
    "diagnoses": ("condition", "finding", "disorder"),
}

_NON_PLURAL_S_WORDS: Final[frozenset[str]] = frozenset({"diabetes", "status", "sepsis"})

TEMPORAL_INTENT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(latest|newest|most\s+recent|recent|last|current)\b",
    re.IGNORECASE,
)


def has_temporal_intent(query: str) -> bool:
    """Return True if the query explicitly indicates temporal/recency intent.

    Matches whole words: 'latest', 'newest', 'most recent', 'recent', 'last',
    or 'current'. Uses word boundaries to avoid false matches (e.g. 'blast',
    'elastic', 'currency', 'crescent').
    """
    if not query:
        return False
    return bool(TEMPORAL_INTENT_PATTERN.search(query))


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
    date_of_service: date | None = None


def normalize_query(query: str) -> tuple[str, ...]:
    """Normalize a search query into deterministic unique terms with synonyms and singulars."""
    cleaned = re.sub(r"[^\w\s]", " ", query.lower())
    tokens = cleaned.split()
    if not tokens:
        return ()

    terms: list[str] = []
    for token in tokens:
        terms.append(token)

        singular: str | None = None
        if (
            token.endswith("s")
            and not token.endswith("ss")
            and len(token) > 4
            and token not in _NON_PLURAL_S_WORDS
        ):
            singular = token[:-1]
            terms.append(singular)

        if token in CLINICAL_SYNONYMS:
            terms.extend(CLINICAL_SYNONYMS[token])
        elif singular and singular in CLINICAL_SYNONYMS:
            terms.extend(CLINICAL_SYNONYMS[singular])

    return tuple(dict.fromkeys(terms))


def lexical_score(content: str, query_terms: tuple[str, ...]) -> int:
    """Score content by the number of query terms it contains."""
    if not query_terms:
        return 0

    normalized_content = content.lower()
    return sum(term in normalized_content for term in query_terms)


def rank_retrieved_chunks(
    chunks: list[RetrievedChunk],
    query: str,
    *,
    limit: int = 10,
) -> list[RetrievedChunk]:
    """Rank candidate RetrievedChunk objects deterministically.

    Ranking policy:
    1. If the query expresses explicit temporal intent (e.g. 'latest', 'recent'):
       - Candidates with strong lexical relevance (Tier 1) are prioritized by
         recency descending (date_of_service), with lexical score as a secondary criterion.
       - Candidates with weak lexical relevance (Tier 0) cannot outrank Tier 1,
         preventing unrelated recent records from displacing relevant clinical evidence.
    2. For non-temporal queries:
       - Higher lexical score strictly outranks lower lexical score.
       - Recency breaks equal-score ties.
    3. Undated/missing-date records sort deterministically after dated records when
       recency ordering applies.
    4. Stable tie-breaking by (document_id, chunk_index, chunk_id) is preserved.
    """
    if limit <= 0 or not chunks:
        return []

    is_temporal = has_temporal_intent(query)
    max_score = max((chunk.score for chunk in chunks), default=0)

    if is_temporal and max_score > 0:
        # Require strong lexical relevance to enter the recency-prioritized tier.
        # This prevents weak matches (e.g. matching only "patient") from outranking
        # core clinical evidence like lab panels or conditions.
        threshold = max(2, int(max_score * 0.6)) if max_score >= 3 else max_score

        def temporal_sort_key(item: RetrievedChunk) -> tuple[int, int, int, str, int, str]:
            date_ord = item.date_of_service.toordinal() if item.date_of_service else -1
            is_tier_1 = 1 if item.score >= threshold else 0
            return (
                -is_tier_1,
                -date_ord,
                -item.score,
                str(item.document_id),
                item.chunk_index,
                str(item.chunk_id),
            )

        return sorted(chunks, key=temporal_sort_key)[:limit]

    def standard_sort_key(item: RetrievedChunk) -> tuple[int, int, str, int, str]:
        date_ord = item.date_of_service.toordinal() if item.date_of_service else -1
        return (
            -item.score,
            -date_ord,
            str(item.document_id),
            item.chunk_index,
            str(item.chunk_id),
        )

    return sorted(chunks, key=standard_sort_key)[:limit]


def rank_chunks(
    chunks: list[AIChunk],
    query: str,
    *,
    limit: int = 10,
    dates_by_document_id: Mapping[UUID, date] | None = None,
) -> list[RetrievedChunk]:
    """Rank candidate chunks deterministically using lexical matching and recency."""
    if limit <= 0:
        return []

    query_terms = normalize_query(query)
    if not query_terms:
        return []

    ranked: list[RetrievedChunk] = []

    for chunk in chunks:
        score = lexical_score(chunk.content, query_terms)
        if score == 0:
            continue

        date_val = (
            dates_by_document_id.get(chunk.document_id)
            if dates_by_document_id is not None
            else None
        )

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
                date_of_service=date_val,
            )
        )

    return rank_retrieved_chunks(ranked, query, limit=limit)
