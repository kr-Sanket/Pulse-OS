"""Tests for provider-agnostic answer generation domain boundary."""

import asyncio
from dataclasses import FrozenInstanceError
from datetime import UTC
from uuid import UUID, uuid4

import pytest
from app.modules.ai.context import AssembledContext, ContextEvidenceItem
from app.modules.ai.generation import (
    AnswerGenerator,
    CitationReference,
    FakeAnswerGenerator,
    GeneratedAnswer,
)


def make_evidence_item(
    *,
    citation_index: int = 1,
    record_id: UUID | None = None,
    category_code: str = "LAB_REPORT",
    chunk_index: int = 0,
    content: str = "Evidence text",
    token_count: int = 20,
) -> ContextEvidenceItem:
    return ContextEvidenceItem(
        chunk_id=uuid4(),
        record_id=record_id or uuid4(),
        category_code=category_code,
        chunk_index=chunk_index,
        content=content,
        token_count=token_count,
        citation_index=citation_index,
    )


def make_assembled_context(
    items: tuple[ContextEvidenceItem, ...] = (),
    *,
    query: str = "patient clinical status",
    patient_id: UUID | None = None,
    total_tokens: int = 0,
    max_tokens: int = 1000,
    is_truncated: bool = False,
    dropped_chunk_count: int = 0,
) -> AssembledContext:
    return AssembledContext(
        query=query,
        patient_id=patient_id or uuid4(),
        items=items,
        total_tokens=total_tokens,
        max_tokens=max_tokens,
        is_truncated=is_truncated,
        dropped_chunk_count=dropped_chunk_count,
    )


def test_fake_answer_generator_returns_expected_structure() -> None:
    generator = FakeAnswerGenerator(answer_template="Custom clinical response [1].")
    item = make_evidence_item(citation_index=1, category_code="LAB_REPORT")
    context = make_assembled_context(items=(item,), total_tokens=20)

    result = asyncio.run(generator.generate_answer(context))

    assert isinstance(result, GeneratedAnswer)
    assert result.answer == "Custom clinical response [1]."
    assert result.provider == "fake"
    assert result.model == "fake-v1"
    assert result.generated_at.tzinfo is not None
    assert result.generated_at.tzinfo == UTC
    assert len(result.citations) == 1
    assert result.citations[0].citation_index == 1
    assert result.citations[0].record_id == item.record_id
    assert result.citations[0].category_code == "LAB_REPORT"
    assert result.citations[0].chunk_index == item.chunk_index


def test_citation_mapping_preserves_context_provenance() -> None:
    generator = FakeAnswerGenerator()

    rec_id_1 = uuid4()
    rec_id_2 = uuid4()
    rec_id_3 = uuid4()

    item1 = make_evidence_item(
        citation_index=1,
        record_id=rec_id_1,
        category_code="LAB_REPORT",
        chunk_index=0,
    )
    item2 = make_evidence_item(
        citation_index=2,
        record_id=rec_id_2,
        category_code="PRESCRIPTION",
        chunk_index=1,
    )
    item3 = make_evidence_item(
        citation_index=3,
        record_id=rec_id_3,
        category_code="DISCHARGE_SUMMARY",
        chunk_index=4,
    )

    context = make_assembled_context(items=(item1, item2, item3), total_tokens=60)

    result = asyncio.run(generator.generate_answer(context))

    assert len(result.citations) == 3

    assert result.citations[0].citation_index == 1
    assert result.citations[0].record_id == rec_id_1
    assert result.citations[0].category_code == "LAB_REPORT"
    assert result.citations[0].chunk_index == 0

    assert result.citations[1].citation_index == 2
    assert result.citations[1].record_id == rec_id_2
    assert result.citations[1].category_code == "PRESCRIPTION"
    assert result.citations[1].chunk_index == 1

    assert result.citations[2].citation_index == 3
    assert result.citations[2].record_id == rec_id_3
    assert result.citations[2].category_code == "DISCHARGE_SUMMARY"
    assert result.citations[2].chunk_index == 4


def test_empty_context_behavior() -> None:
    generator = FakeAnswerGenerator()
    empty_context = make_assembled_context(items=(), total_tokens=0)

    result = asyncio.run(generator.generate_answer(empty_context))

    assert isinstance(result, GeneratedAnswer)
    assert result.citations == ()
    assert result.provider == "fake"
    assert result.model == "fake-v1"
    assert result.answer == "Based on the available evidence [1]."


def test_generation_contract_immutability() -> None:
    citation = CitationReference(
        citation_index=1,
        record_id=uuid4(),
        category_code="LAB_REPORT",
        chunk_index=0,
    )
    answer = GeneratedAnswer(
        answer="Frozen answer",
        citations=(citation,),
        provider="fake",
        model="fake-v1",
        generated_at=make_assembled_context().query,  # type: ignore[arg-type]
    )

    with pytest.raises(FrozenInstanceError):
        citation.citation_index = 2  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        answer.provider = "other"  # type: ignore[misc]


def test_fake_generator_records_exact_context() -> None:
    generator = FakeAnswerGenerator()
    item = make_evidence_item(citation_index=1)
    context = make_assembled_context(items=(item,), query="test query")

    assert len(generator.calls) == 0

    result = asyncio.run(generator.generate_answer(context))
    assert result is not None

    assert len(generator.calls) == 1
    assert generator.calls[0] is context
    assert generator.calls[0].query == "test query"
    assert generator.calls[0].items == (item,)


def test_answer_generator_protocol_compliance() -> None:
    fake = FakeAnswerGenerator()

    # Runtime checkable protocol
    assert isinstance(fake, AnswerGenerator)

    # Static type compatibility
    generator: AnswerGenerator = fake
    assert callable(generator.generate_answer)
