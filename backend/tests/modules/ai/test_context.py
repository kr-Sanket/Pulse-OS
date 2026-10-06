"""Tests for deterministic AI context assembly."""

from dataclasses import FrozenInstanceError, fields
from uuid import UUID, uuid4

import pytest

from app.modules.ai.context import (
    AssembledContext,
    ContextAudience,
    ContextEvidenceItem,
    assemble_context,
)
from app.modules.ai.retrieval import RetrievedChunk


def make_retrieved_chunk(
    *,
    chunk_id: UUID | None = None,
    document_id: UUID | None = None,
    record_id: UUID | None = None,
    patient_id: UUID | None = None,
    category_id: UUID | None = None,
    chunk_index: int = 0,
    content: str = "Test clinical chunk content",
    content_hash: str = "abc123hash",
    token_count: int = 20,
    score: int = 5,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id or uuid4(),
        document_id=document_id or uuid4(),
        record_id=record_id or uuid4(),
        patient_id=patient_id or uuid4(),
        category_id=category_id or uuid4(),
        chunk_index=chunk_index,
        content=content,
        content_hash=content_hash,
        token_count=token_count,
        score=score,
    )


def test_basic_assembly_with_multiple_chunks():
    patient_id = uuid4()
    cat_id_1 = uuid4()
    cat_id_2 = uuid4()
    category_codes = {cat_id_1: "LAB_REPORT", cat_id_2: "PRESCRIPTION"}

    chunk1 = make_retrieved_chunk(
        category_id=cat_id_1,
        content="Glucose level 110 mg/dL",
        token_count=30,
        chunk_index=0,
    )
    chunk2 = make_retrieved_chunk(
        category_id=cat_id_2,
        content="Metformin 500mg daily",
        token_count=25,
        chunk_index=1,
    )

    context = assemble_context(
        query="glucose metformin",
        patient_id=patient_id,
        chunks=[chunk1, chunk2],
        category_codes=category_codes,
        max_tokens=1000,
    )

    assert isinstance(context, AssembledContext)
    assert context.query == "glucose metformin"
    assert context.patient_id == patient_id
    assert len(context.items) == 2
    assert context.total_tokens == 55
    assert context.max_tokens == 1000
    assert context.is_truncated is False
    assert context.dropped_chunk_count == 0

    item1 = context.items[0]
    assert item1.chunk_id == chunk1.chunk_id
    assert item1.record_id == chunk1.record_id
    assert item1.category_code == "LAB_REPORT"
    assert item1.chunk_index == 0
    assert item1.content == "Glucose level 110 mg/dL"
    assert item1.token_count == 30
    assert item1.citation_index == 1

    item2 = context.items[1]
    assert item2.chunk_id == chunk2.chunk_id
    assert item2.record_id == chunk2.record_id
    assert item2.category_code == "PRESCRIPTION"
    assert item2.chunk_index == 1
    assert item2.content == "Metformin 500mg daily"
    assert item2.token_count == 25
    assert item2.citation_index == 2


def test_input_order_preservation():
    patient_id = uuid4()
    cat_id = uuid4()
    category_codes = {cat_id: "CONSULTATION_NOTE"}

    chunks = [
        make_retrieved_chunk(
            category_id=cat_id,
            content=f"Rank {i} chunk content",
            token_count=15,
            chunk_index=i,
        )
        for i in range(4)
    ]

    context = assemble_context(
        query="consultation note",
        patient_id=patient_id,
        chunks=chunks,
        category_codes=category_codes,
        max_tokens=500,
    )

    assert len(context.items) == 4
    for i in range(4):
        assert context.items[i].chunk_id == chunks[i].chunk_id
        assert context.items[i].content == f"Rank {i} chunk content"
        assert context.items[i].citation_index == i + 1


def test_token_budget_allows_only_fitting_chunks():
    patient_id = uuid4()
    cat_id = uuid4()
    category_codes = {cat_id: "DISCHARGE_SUMMARY"}

    chunk1 = make_retrieved_chunk(category_id=cat_id, token_count=40)
    chunk2 = make_retrieved_chunk(category_id=cat_id, token_count=40)
    chunk3 = make_retrieved_chunk(category_id=cat_id, token_count=40)

    # Budget of 90 allows chunk1 (40) and chunk2 (40) = 80, but not chunk3 (120 > 90)
    context = assemble_context(
        query="discharge summary",
        patient_id=patient_id,
        chunks=[chunk1, chunk2, chunk3],
        category_codes=category_codes,
        max_tokens=90,
    )

    assert len(context.items) == 2
    assert context.total_tokens == 80
    assert context.total_tokens <= context.max_tokens
    assert context.items[0].chunk_id == chunk1.chunk_id
    assert context.items[1].chunk_id == chunk2.chunk_id
    assert context.is_truncated is True
    assert context.dropped_chunk_count == 1


def test_truncation_stops_further_processing_and_excludes_subsequent_chunks():
    patient_id = uuid4()
    cat_id = uuid4()
    category_codes = {cat_id: "LAB_REPORT"}

    chunk1 = make_retrieved_chunk(category_id=cat_id, token_count=50)
    chunk2 = make_retrieved_chunk(category_id=cat_id, token_count=60)  # Exceeds 100
    chunk3 = make_retrieved_chunk(category_id=cat_id, token_count=10)  # Even though 10 fits 50+10, it must be excluded
    chunk4 = make_retrieved_chunk(category_id=cat_id, token_count=10)

    context = assemble_context(
        query="lab report",
        patient_id=patient_id,
        chunks=[chunk1, chunk2, chunk3, chunk4],
        category_codes=category_codes,
        max_tokens=100,
    )

    assert len(context.items) == 1
    assert context.items[0].chunk_id == chunk1.chunk_id
    assert context.total_tokens == 50
    assert context.is_truncated is True
    assert context.dropped_chunk_count == 3


def test_exact_fit_boundary():
    patient_id = uuid4()
    cat_id = uuid4()
    category_codes = {cat_id: "IMAGING"}

    chunk1 = make_retrieved_chunk(category_id=cat_id, token_count=60)
    chunk2 = make_retrieved_chunk(category_id=cat_id, token_count=40)

    context = assemble_context(
        query="xray chest",
        patient_id=patient_id,
        chunks=[chunk1, chunk2],
        category_codes=category_codes,
        max_tokens=100,
    )

    assert len(context.items) == 2
    assert context.total_tokens == 100
    assert context.max_tokens == 100
    assert context.is_truncated is False
    assert context.dropped_chunk_count == 0


def test_single_oversized_chunk():
    patient_id = uuid4()
    cat_id = uuid4()
    category_codes = {cat_id: "LAB_REPORT"}

    chunk = make_retrieved_chunk(category_id=cat_id, token_count=150)

    context = assemble_context(
        query="oversized",
        patient_id=patient_id,
        chunks=[chunk],
        category_codes=category_codes,
        max_tokens=100,
    )

    assert len(context.items) == 0
    assert context.items == ()
    assert context.total_tokens == 0
    assert context.is_truncated is True
    assert context.dropped_chunk_count == 1


def test_empty_chunks_returns_empty_context():
    patient_id = uuid4()

    context = assemble_context(
        query="no chunks query",
        patient_id=patient_id,
        chunks=[],
        category_codes={},
        max_tokens=1000,
    )

    assert context.query == "no chunks query"
    assert context.patient_id == patient_id
    assert context.items == ()
    assert context.total_tokens == 0
    assert context.max_tokens == 1000
    assert context.is_truncated is False
    assert context.dropped_chunk_count == 0


@pytest.mark.parametrize("invalid_budget", [0, -1, -500])
def test_invalid_budget_raises_value_error(invalid_budget: int):
    patient_id = uuid4()

    with pytest.raises(ValueError, match="max_tokens must be greater than zero"):
        assemble_context(
            query="test",
            patient_id=patient_id,
            chunks=[],
            category_codes={},
            max_tokens=invalid_budget,
        )


def test_missing_category_mapping_raises_key_error():
    patient_id = uuid4()
    missing_cat_id = uuid4()
    chunk = make_retrieved_chunk(category_id=missing_cat_id, token_count=20)

    with pytest.raises(KeyError):
        assemble_context(
            query="test",
            patient_id=patient_id,
            chunks=[chunk],
            category_codes={},  # Empty mapping lacks missing_cat_id
            max_tokens=100,
        )


def test_security_and_data_minimization():
    field_names = {f.name for f in fields(ContextEvidenceItem)}
    expected_fields = {
        "chunk_id",
        "record_id",
        "category_code",
        "chunk_index",
        "content",
        "token_count",
        "citation_index",
    }
    assert field_names == expected_fields

    forbidden_fields = {
        "document_id",
        "category_id",
        "content_hash",
        "score",
        "s3_key",
        "original_filename",
        "consent_id",
        "event_hash",
        "firebase_uid",
        "email",
    }
    assert field_names.isdisjoint(forbidden_fields)

    patient_id = uuid4()
    cat_id = uuid4()
    chunk = make_retrieved_chunk(category_id=cat_id, token_count=10)
    context = assemble_context(
        query="security test",
        patient_id=patient_id,
        chunks=[chunk],
        category_codes={cat_id: "LAB_REPORT"},
        max_tokens=100,
    )
    assert len(context.items) == 1
    item = context.items[0]
    for forbidden in forbidden_fields:
        assert not hasattr(item, forbidden)


def test_query_and_patient_id_are_preserved_verbatim():
    patient_id = uuid4()
    exact_query = "   Spaces  and UPPERCASE with ?!! punctuation   "

    context = assemble_context(
        query=exact_query,
        patient_id=patient_id,
        chunks=[],
        category_codes={},
        max_tokens=500,
    )

    assert context.query == exact_query
    assert context.patient_id == patient_id


def test_dataclasses_are_frozen():
    patient_id = uuid4()
    cat_id = uuid4()
    chunk = make_retrieved_chunk(category_id=cat_id, token_count=10)
    context = assemble_context(
        query="frozen test",
        patient_id=patient_id,
        chunks=[chunk],
        category_codes={cat_id: "LAB_REPORT"},
        max_tokens=100,
    )

    with pytest.raises(FrozenInstanceError):
        context.total_tokens = 99  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        context.items[0].citation_index = 99  # type: ignore[misc]


def test_assemble_context_defaults_to_clinician_audience():
    patient_id = uuid4()
    cat_id = uuid4()
    chunk = make_retrieved_chunk(category_id=cat_id, token_count=10)
    context = assemble_context(
        query="audience test",
        patient_id=patient_id,
        chunks=[chunk],
        category_codes={cat_id: "LAB_REPORT"},
    )
    assert context.audience == ContextAudience.CLINICIAN


def test_assemble_context_preserves_explicit_patient_audience():
    patient_id = uuid4()
    cat_id = uuid4()
    chunk = make_retrieved_chunk(category_id=cat_id, token_count=10)
    context = assemble_context(
        query="patient audience test",
        patient_id=patient_id,
        chunks=[chunk],
        category_codes={cat_id: "LAB_REPORT"},
        audience=ContextAudience.PATIENT,
    )
    assert context.audience == ContextAudience.PATIENT


def test_assemble_context_preserves_explicit_clinician_audience():
    patient_id = uuid4()
    cat_id = uuid4()
    chunk = make_retrieved_chunk(category_id=cat_id, token_count=10)
    context = assemble_context(
        query="clinician audience test",
        patient_id=patient_id,
        chunks=[chunk],
        category_codes={cat_id: "LAB_REPORT"},
        audience=ContextAudience.CLINICIAN,
    )
    assert context.audience == ContextAudience.CLINICIAN


def test_assembled_context_dataclass_default_audience():
    context = AssembledContext(
        query="direct test",
        patient_id=uuid4(),
        items=(),
        total_tokens=0,
        max_tokens=1000,
        is_truncated=False,
        dropped_chunk_count=0,
    )
    assert context.audience == ContextAudience.CLINICIAN


def test_audience_does_not_affect_token_budget_or_citations():
    patient_id = uuid4()
    cat_id = uuid4()
    chunk1 = make_retrieved_chunk(category_id=cat_id, token_count=40, chunk_index=0)
    chunk2 = make_retrieved_chunk(category_id=cat_id, token_count=40, chunk_index=1)

    clinician_ctx = assemble_context(
        query="same query",
        patient_id=patient_id,
        chunks=[chunk1, chunk2],
        category_codes={cat_id: "LAB_REPORT"},
        max_tokens=50,
        audience=ContextAudience.CLINICIAN,
    )

    patient_ctx = assemble_context(
        query="same query",
        patient_id=patient_id,
        chunks=[chunk1, chunk2],
        category_codes={cat_id: "LAB_REPORT"},
        max_tokens=50,
        audience=ContextAudience.PATIENT,
    )

    assert clinician_ctx.total_tokens == patient_ctx.total_tokens == 40
    assert clinician_ctx.is_truncated is True
    assert patient_ctx.is_truncated is True
    assert clinician_ctx.dropped_chunk_count == patient_ctx.dropped_chunk_count == 1
    assert len(clinician_ctx.items) == len(patient_ctx.items) == 1
    assert clinician_ctx.items[0].citation_index == patient_ctx.items[0].citation_index == 1

