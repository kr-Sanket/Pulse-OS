from datetime import date
from uuid import uuid4

from app.modules.ai.models import AIChunk
from app.modules.ai.retrieval import (
    has_temporal_intent,
    lexical_score,
    normalize_query,
    rank_chunks,
)


def test_normalize_query_lowercases_and_deduplicates_terms() -> None:
    assert normalize_query("Diabetes diabetes ACTIVE") == (
        "diabetes",
        "active",
    )


def test_normalize_query_ignores_whitespace() -> None:
    assert normalize_query("  diabetes   active  ") == (
        "diabetes",
        "active",
    )


def test_lexical_score_counts_matching_terms() -> None:
    terms = normalize_query("diabetes active")

    assert lexical_score(
        "Condition: Diabetes\nClinical Status: active",
        terms,
    ) == 2


def test_lexical_score_is_case_insensitive() -> None:
    terms = normalize_query("Diabetes")

    assert lexical_score("condition: DIABETES", terms) == 1


def test_empty_query_has_zero_score() -> None:
    assert lexical_score("some clinical text", ()) == 0


def test_unmatched_query_has_zero_score() -> None:
    terms = normalize_query("hypertension")

    assert lexical_score("Condition: Diabetes", terms) == 0


def test_lexical_score_does_not_reward_repeated_occurrences() -> None:
    terms = normalize_query("diabetes active")

    assert lexical_score(
        "diabetes diabetes diabetes active",
        terms,
    ) == 2


def test_vaccination_matches_immunization_vaccine_content() -> None:
    terms = normalize_query("vaccination")
    assert "vaccine" in terms
    assert "immunization" in terms
    assert lexical_score("Resource: Immunization\nVaccine: COVID-19 mRNA", terms) >= 1


def test_vaccinations_matches_immunization_vaccine_content() -> None:
    terms = normalize_query("vaccinations")
    assert "vaccine" in terms
    assert "immunization" in terms
    assert lexical_score("Resource: Immunization\nVaccine: Influenza", terms) >= 1


def test_vaccinated_matches_immunization_vaccine_content() -> None:
    terms = normalize_query("vaccinated")
    assert "vaccine" in terms
    assert "immunization" in terms
    assert lexical_score("Resource: Immunization\nVaccine: Hepatitis B", terms) >= 1


def test_lab_reports_matches_diagnostic_report_metabolic_panel_content() -> None:
    terms = normalize_query("lab reports")
    assert "diagnosticreport" in terms
    assert "panel" in terms
    content = "Resource: DiagnosticReport\nName: Basic Metabolic Panel\nStatus: final"
    assert lexical_score(content, terms) >= 2


def test_punctuation_does_not_break_matching() -> None:
    assert lexical_score("Vaccine administered", normalize_query("vaccination?")) >= 1
    assert lexical_score("DiagnosticReport available", normalize_query("reports.")) >= 1
    assert lexical_score("MedicationRequest active", normalize_query("medications!")) >= 1


def test_existing_exact_matching_remains_unchanged() -> None:
    terms = normalize_query("diabetes")
    assert lexical_score("Condition: Diabetes", terms) == 1


def test_duplicate_query_terms_remain_deterministic() -> None:
    res1 = normalize_query("vaccination vaccination vaccine")
    res2 = normalize_query("vaccination vaccine")
    assert res1 == res2
    assert isinstance(res1, tuple)


def test_carcinoma_does_not_accidentally_match_cardiac() -> None:
    terms = normalize_query("carcinoma")
    assert "cardiac" not in terms
    assert lexical_score("Cardiac examination normal", terms) == 0


def test_appendix_does_not_accidentally_match_appendix_table() -> None:
    terms = normalize_query("appendix_table")
    assert lexical_score("Condition: appendix removed", terms) == 0
    assert "appendix_table" not in normalize_query("appendix")


def test_existing_score_ordering_remains_deterministic() -> None:
    patient_id = uuid4()
    cat_id = uuid4()
    doc1 = uuid4()
    doc2 = uuid4()

    chunk_high = AIChunk(
        id=uuid4(),
        document_id=doc1,
        patient_id=patient_id,
        category_id=cat_id,
        chunk_index=0,
        content="Immunization vaccine administered on schedule",
        content_hash="h1",
        token_count=10,
    )
    chunk_low = AIChunk(
        id=uuid4(),
        document_id=doc2,
        patient_id=patient_id,
        category_id=cat_id,
        chunk_index=0,
        content="Vaccine record reviewed",
        content_hash="h2",
        token_count=8,
    )

    ranked = rank_chunks([chunk_low, chunk_high], "vaccination")
    assert len(ranked) == 2
    assert ranked[0].score > ranked[1].score
    assert ranked[0].chunk_id == chunk_high.id


def test_temporal_intent_classifier() -> None:
    # Covered temporal keywords
    assert has_temporal_intent("What are the patient's latest laboratory results?") is True
    assert has_temporal_intent("Show newest diagnostic reports") is True
    assert has_temporal_intent("Most recent findings") is True
    assert has_temporal_intent("Recent lipid panels") is True
    assert has_temporal_intent("What was the last prescription?") is True
    assert has_temporal_intent("List current active medications") is True

    # Case-insensitive
    assert has_temporal_intent("LATEST LAB RESULTS") is True

    # Boundary safety: avoid matches inside unrelated words
    assert has_temporal_intent("Blast injury sustained") is False
    assert has_temporal_intent("Elastic bandage applied") is False
    assert has_temporal_intent("Currency exchange completed") is False
    assert has_temporal_intent("Crescent sign observed on imaging") is False
    assert has_temporal_intent("Patient has diabetes and hypertension") is False
    assert has_temporal_intent("") is False


def test_t1_temporal_query_newer_record_outranks_older_with_equal_score() -> None:
    patient_id = uuid4()
    cat_id = uuid4()
    doc_old = uuid4()
    doc_new = uuid4()

    chunk_old = AIChunk(
        id=uuid4(),
        document_id=doc_old,
        patient_id=patient_id,
        category_id=cat_id,
        chunk_index=0,
        content="DiagnosticReport Basic Metabolic Panel lab result",
        content_hash="h_old",
        token_count=10,
    )
    chunk_new = AIChunk(
        id=uuid4(),
        document_id=doc_new,
        patient_id=patient_id,
        category_id=cat_id,
        chunk_index=0,
        content="DiagnosticReport Basic Metabolic Panel lab result",
        content_hash="h_new",
        token_count=10,
    )

    dates = {
        doc_old: date(2017, 9, 24),
        doc_new: date(2018, 10, 1),
    }

    # Pass in reverse order to ensure sorting does the work
    ranked = rank_chunks(
        [chunk_old, chunk_new],
        "What are the patient's latest laboratory results?",
        dates_by_document_id=dates,
    )

    assert len(ranked) == 2
    assert ranked[0].score == ranked[1].score
    # Newer 2018 record ranks first
    assert ranked[0].document_id == doc_new
    assert ranked[0].date_of_service == date(2018, 10, 1)
    assert ranked[1].document_id == doc_old
    assert ranked[1].date_of_service == date(2017, 9, 24)


def test_t2_nontemporal_query_higher_relevance_beats_recency() -> None:
    patient_id = uuid4()
    cat_id = uuid4()
    doc_relevant_old = uuid4()
    doc_weak_new = uuid4()

    # Highly relevant to "diabetes active condition" but older
    chunk_relevant_old = AIChunk(
        id=uuid4(),
        document_id=doc_relevant_old,
        patient_id=patient_id,
        category_id=cat_id,
        chunk_index=0,
        content="Condition: diabetes mellitus active condition diagnosis",
        content_hash="h_rel",
        token_count=10,
    )
    # Weakly relevant but newer
    chunk_weak_new = AIChunk(
        id=uuid4(),
        document_id=doc_weak_new,
        patient_id=patient_id,
        category_id=cat_id,
        chunk_index=0,
        content="Condition: diabetes reviewed",
        content_hash="h_weak",
        token_count=8,
    )

    dates = {
        doc_relevant_old: date(2012, 5, 10),
        doc_weak_new: date(2025, 1, 1),
    }

    ranked = rank_chunks(
        [chunk_weak_new, chunk_relevant_old],
        "diabetes active condition",
        dates_by_document_id=dates,
    )

    assert len(ranked) == 2
    # Score strictly beats date for non-temporal query
    assert ranked[0].score > ranked[1].score
    assert ranked[0].document_id == doc_relevant_old
    assert ranked[1].document_id == doc_weak_new


def test_t3_temporal_query_weak_recent_match_does_not_outrank_relevant_evidence() -> None:
    patient_id = uuid4()
    cat_id = uuid4()
    doc_lab_2017 = uuid4()
    doc_allergy_2018 = uuid4()

    # Strongly relevant lab report from 2017 (matches diagnosticreport, panel, lab, result)
    chunk_lab = AIChunk(
        id=uuid4(),
        document_id=doc_lab_2017,
        patient_id=patient_id,
        category_id=cat_id,
        chunk_index=0,
        content="DiagnosticReport Basic Metabolic Panel lab result report",
        content_hash="h_lab",
        token_count=10,
    )
    # Weak match from 2018 (matches only the word "patient")
    chunk_weak = AIChunk(
        id=uuid4(),
        document_id=doc_allergy_2018,
        patient_id=patient_id,
        category_id=cat_id,
        chunk_index=0,
        content="AllergyIntolerance patient egg allergy",
        content_hash="h_weak",
        token_count=8,
    )

    dates = {
        doc_lab_2017: date(2017, 9, 24),
        doc_allergy_2018: date(2018, 10, 1),
    }

    ranked = rank_chunks(
        [chunk_weak, chunk_lab],
        "What are the patient's latest laboratory results?",
        dates_by_document_id=dates,
    )

    assert len(ranked) == 2
    # The strongly relevant lab chunk must rank ahead of the weak single-token match
    assert ranked[0].document_id == doc_lab_2017
    assert ranked[0].score > ranked[1].score
    assert ranked[1].document_id == doc_allergy_2018


def test_t4_missing_dates_sort_deterministically_after_dated_records() -> None:
    patient_id = uuid4()
    cat_id = uuid4()
    doc_dated = uuid4()
    doc_undated_a = uuid4()
    doc_undated_b = uuid4()

    chunk_dated = AIChunk(
        id=uuid4(),
        document_id=doc_dated,
        patient_id=patient_id,
        category_id=cat_id,
        chunk_index=0,
        content="DiagnosticReport Lipid Panel lab result",
        content_hash="h1",
        token_count=10,
    )
    chunk_undated_a = AIChunk(
        id=uuid4(),
        document_id=doc_undated_a,
        patient_id=patient_id,
        category_id=cat_id,
        chunk_index=0,
        content="DiagnosticReport Lipid Panel lab result",
        content_hash="h2",
        token_count=10,
    )
    chunk_undated_b = AIChunk(
        id=uuid4(),
        document_id=doc_undated_b,
        patient_id=patient_id,
        category_id=cat_id,
        chunk_index=0,
        content="DiagnosticReport Lipid Panel lab result",
        content_hash="h3",
        token_count=10,
    )

    dates = {doc_dated: date(2018, 10, 1)}

    ranked = rank_chunks(
        [chunk_undated_a, chunk_dated, chunk_undated_b],
        "latest laboratory results",
        dates_by_document_id=dates,
    )

    assert len(ranked) == 3
    # Dated record is first
    assert ranked[0].document_id == doc_dated
    assert ranked[0].date_of_service == date(2018, 10, 1)

    # Undated records sort deterministically by document UUID
    assert ranked[1].date_of_service is None
    assert ranked[2].date_of_service is None
    expected_order = sorted([doc_undated_a, doc_undated_b], key=str)
    assert ranked[1].document_id == expected_order[0]
    assert ranked[2].document_id == expected_order[1]
