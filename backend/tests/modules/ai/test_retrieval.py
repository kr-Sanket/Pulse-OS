from uuid import uuid4

from app.modules.ai.models import AIChunk
from app.modules.ai.retrieval import lexical_score, normalize_query, rank_chunks


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