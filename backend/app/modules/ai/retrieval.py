"""Deterministic AI chunk retrieval primitives."""

from __future__ import annotations

import re
from dataclasses import dataclass
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