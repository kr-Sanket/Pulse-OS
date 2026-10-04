"""AI/RAG-owned persistence tables.

The AI module stores derived representations of medical records for future
retrieval and generation. Clinical source data remains owned by the records
module; these tables contain only derived AI documents and chunks.

Cross-module links are plain UUID foreign keys — no SQLAlchemy relationships.
"""

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AIDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One AI-indexable representation of a MedicalRecord.

    There is exactly one AI document per medical record. The document stores
    provenance and source-version information; the actual normalized clinical
    text is represented by AIChunk rows.
    """

    __tablename__ = "ai_documents"

    record_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("medical_records.id"),
        unique=True,
        nullable=False,
        index=True,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("patients.id"),
        nullable=False,
        index=True,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("record_categories.id"),
        nullable=False,
        index=True,
    )
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    source_version: Mapped[int] = mapped_column(
        Integer(),
        nullable=False,
        default=1,
    )


class AIChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One deterministic text chunk derived from an AI document."""

    __tablename__ = "ai_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("ai_documents.id"),
        nullable=False,
        index=True,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("patients.id"),
        nullable=False,
        index=True,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("record_categories.id"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(
        Integer(),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(
        Text(),
        nullable=False,
    )
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    token_count: Mapped[int] = mapped_column(
        Integer(),
        nullable=False,
    )