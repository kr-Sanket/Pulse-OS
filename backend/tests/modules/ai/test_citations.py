"""Answer text and returned citations must agree with the supplied evidence (ai/citations.py)."""

from datetime import UTC, datetime
from uuid import uuid4

from app.modules.ai.citations import reconcile_citations
from app.modules.ai.context import AssembledContext, ContextEvidenceItem
from app.modules.ai.generation import CitationReference, GeneratedAnswer


def _context(n: int) -> AssembledContext:
    items = tuple(
        ContextEvidenceItem(
            chunk_id=uuid4(),
            record_id=uuid4(),
            category_code="CBC",
            chunk_index=i,
            content=f"evidence {i}",
            token_count=2,
            citation_index=i + 1,
        )
        for i in range(n)
    )
    return AssembledContext(
        query="q",
        patient_id=uuid4(),
        items=items,
        total_tokens=2 * n,
        max_tokens=100,
        is_truncated=False,
        dropped_chunk_count=0,
    )


def _answer(text: str, cited: list[int], context: AssembledContext) -> GeneratedAnswer:
    forged = uuid4()  # a generator-supplied record id must never survive reconciliation
    return GeneratedAnswer(
        answer=text,
        citations=tuple(
            CitationReference(citation_index=i, record_id=forged, category_code="X", chunk_index=0)
            for i in cited
        ),
        provider="fake",
        model="fake-v1",
        generated_at=datetime.now(UTC),
    )


def test_citations_are_exactly_the_valid_markers_in_the_text() -> None:
    context = _context(3)
    result = reconcile_citations(
        _answer("Hb is low [2]. WBC normal [1].", [1, 2, 3], context), context
    )
    assert [c.citation_index for c in result.citations] == [1, 2]
    assert result.answer == "Hb is low [2]. WBC normal [1]."


def test_markers_naming_missing_evidence_are_removed_from_the_text() -> None:
    context = _context(2)
    result = reconcile_citations(
        _answer("Hb is low [7]. WBC normal [1].", [7, 1], context), context
    )
    assert result.answer == "Hb is low. WBC normal [1]."
    assert [c.citation_index for c in result.citations] == [1]


def test_grouped_markers_keep_only_supported_indices() -> None:
    context = _context(2)
    result = reconcile_citations(_answer("Both agree [1, 9, 2].", [], context), context)
    assert result.answer == "Both agree [1, 2]."
    assert [c.citation_index for c in result.citations] == [1, 2]


def test_listed_indices_without_a_marker_are_not_citations() -> None:
    context = _context(3)
    result = reconcile_citations(_answer("No markers at all.", [1, 2, 3], context), context)
    assert result.citations == ()
    assert result.answer == "No markers at all."


def test_citations_are_rebuilt_from_the_supplied_evidence() -> None:
    context = _context(2)
    result = reconcile_citations(_answer("See [2].", [2], context), context)
    (citation,) = result.citations
    assert citation.record_id == context.items[1].record_id
    assert citation.category_code == "CBC"
    assert citation.chunk_index == 1


def test_non_marker_brackets_and_metadata_are_untouched() -> None:
    context = _context(1)
    generated = _answer("Ratio [high] noted [1].", [1], context)
    result = reconcile_citations(generated, context)
    assert result.answer == "Ratio [high] noted [1]."
    assert (result.provider, result.model, result.generated_at) == (
        generated.provider,
        generated.model,
        generated.generated_at,
    )
