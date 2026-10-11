"""Deterministic text chunking and content hashing for AI/RAG ingestion."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkPayload:
    """One deterministic AI chunk."""

    chunk_index: int
    content: str
    content_hash: str
    token_count: int


@dataclass(frozen=True)
class DocumentPayload:
    """Deterministic AI document representation."""

    content_hash: str
    source_version: int
    chunks: tuple[ChunkPayload, ...]


def sha256_text(content: str) -> str:
    """Return the lowercase SHA-256 digest of UTF-8 text."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def estimate_token_count(content: str) -> int:
    """Return a deterministic lightweight token-count estimate.

    A real tokenizer will be introduced with the embedding layer. For A1,
    whitespace-token counting is sufficient and keeps this layer dependency-free.
    """
    return len(content.split())


def chunk_text(
    text: str,
    *,
    max_tokens: int = 120,
) -> tuple[ChunkPayload, ...]:
    """Split text deterministically into whitespace-token chunks.

    The same input and max_tokens always produce the same chunks.
    """
    if max_tokens <= 0:
        raise ValueError("max_tokens must be greater than zero")

    normalized = text.strip()

    if not normalized:
        return ()

    words = normalized.split()
    chunks: list[ChunkPayload] = []

    for start in range(0, len(words), max_tokens):
        content = " ".join(words[start : start + max_tokens])

        chunks.append(
            ChunkPayload(
                chunk_index=len(chunks),
                content=content,
                content_hash=sha256_text(content),
                token_count=estimate_token_count(content),
            )
        )

    return tuple(chunks)


def build_document_payload(
    text: str,
    *,
    source_version: int = 1,
    max_tokens: int = 120,
) -> DocumentPayload:
    """Build a deterministic AI document payload from normalized text."""
    if source_version <= 0:
        raise ValueError("source_version must be greater than zero")

    normalized = text.strip()

    return DocumentPayload(
        content_hash=sha256_text(normalized),
        source_version=source_version,
        chunks=chunk_text(
            normalized,
            max_tokens=max_tokens,
        ),
    )
