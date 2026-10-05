from uuid import uuid4

from app.modules.ai.retrieval import lexical_score, normalize_query


def test_normalize_query_lowercases_and_deduplicates_terms():
    assert normalize_query("Diabetes diabetes ACTIVE") == (
        "diabetes",
        "active",
    )


def test_normalize_query_ignores_whitespace():
    assert normalize_query("  diabetes   active  ") == (
        "diabetes",
        "active",
    )


def test_lexical_score_counts_matching_terms():
    terms = normalize_query("diabetes active")

    assert lexical_score(
        "Condition: Diabetes\nClinical Status: active",
        terms,
    ) == 2


def test_lexical_score_is_case_insensitive():
    terms = normalize_query("Diabetes")

    assert lexical_score("condition: DIABETES", terms) == 1


def test_empty_query_has_zero_score():
    assert lexical_score("some clinical text", ()) == 0


def test_unmatched_query_has_zero_score():
    terms = normalize_query("hypertension")

    assert lexical_score("Condition: Diabetes", terms) == 0

def test_lexical_score_does_not_reward_repeated_occurrences():
    terms = normalize_query("diabetes active")

    assert lexical_score(
        "diabetes diabetes diabetes active",
        terms,
    ) == 2