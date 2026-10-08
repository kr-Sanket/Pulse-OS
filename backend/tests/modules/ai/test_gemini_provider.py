"""Tests for modular Gemini AnswerGenerator provider adapter."""

import asyncio
from datetime import timezone
from typing import Any
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.modules.ai.context import AssembledContext, ContextAudience, ContextEvidenceItem
from app.modules.ai.dependencies import get_answer_generator
from app.modules.ai.generation import AnswerGenerator, FakeAnswerGenerator, GeneratedAnswer
from app.modules.ai.providers.gemini import (
    DEFAULT_GEMINI_TIMEOUT_SECONDS,
    EMPTY_EVIDENCE_ANSWER,
    GeminiAnswerGenerator,
    GeminiAnswerPayload,
    GeminiProviderError,
    GeminiRateLimitError,
    GeminiSafetyError,
    GeminiTimeoutError,
    GeminiUnavailableError,
    format_gemini_prompt,
    format_patient_copilot_prompt,
)


class MockCandidate:
    def __init__(self, finish_reason: str = "STOP") -> None:
        self.finish_reason = finish_reason


class MockGenerateContentResponse:
    def __init__(
        self,
        parsed: Any = None,
        text: str | None = None,
        candidates: list[Any] | None = None,
    ) -> None:
        self.parsed = parsed
        self.text = text
        self.candidates = candidates or [MockCandidate("STOP")]


class MockAsyncModels:
    def __init__(
        self,
        response: Any = None,
        side_effect: Exception | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self.response = response
        self.side_effect = side_effect
        self.delay_seconds = delay_seconds
        self.calls: list[dict[str, Any]] = []

    async def generate_content(
        self,
        *,
        model: str,
        contents: str,
        config: Any = None,
    ) -> Any:
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.delay_seconds > 0:
            await asyncio.sleep(self.delay_seconds)
        if self.side_effect:
            raise self.side_effect
        return self.response


class MockAsyncClient:
    def __init__(
        self,
        response: Any = None,
        side_effect: Exception | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self.models = MockAsyncModels(
            response=response,
            side_effect=side_effect,
            delay_seconds=delay_seconds,
        )


class MockGeminiClient:
    def __init__(
        self,
        response: Any = None,
        side_effect: Exception | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self.aio = MockAsyncClient(
            response=response,
            side_effect=side_effect,
            delay_seconds=delay_seconds,
        )


def make_evidence_item(
    *,
    citation_index: int = 1,
    record_id=None,
    category_code: str = "LAB_REPORT",
    chunk_index: int = 0,
    content: str = "Fasting glucose is 105 mg/dL",
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
    query: str = "What is the patient's glucose level?",
    patient_id=None,
    audience: ContextAudience = ContextAudience.CLINICIAN,
) -> AssembledContext:
    return AssembledContext(
        query=query,
        patient_id=patient_id or uuid4(),
        items=items,
        total_tokens=sum(item.token_count for item in items),
        max_tokens=1000,
        is_truncated=False,
        dropped_chunk_count=0,
        audience=audience,
    )


def test_gemini_provider_implements_answer_generator():
    client = MockGeminiClient()
    generator = GeminiAnswerGenerator(client=client, model="gemini-3.8-flash")

    assert isinstance(generator, AnswerGenerator)
    assert generator.model == "gemini-3.8-flash"


def test_empty_context_does_not_call_gemini():
    client = MockGeminiClient()
    generator = GeminiAnswerGenerator(client=client, model="gemini-3.8-flash")
    context = make_assembled_context(items=())

    result = asyncio.run(generator.generate_answer(context))

    assert len(client.aio.models.calls) == 0
    assert isinstance(result, GeneratedAnswer)
    assert result.answer == EMPTY_EVIDENCE_ANSWER
    assert result.citations == ()
    assert result.provider == "gemini"
    assert result.model == "gemini-3.8-flash"
    assert result.generated_at.tzinfo == timezone.utc


def test_prompt_contains_only_allowed_model_data():
    item1 = make_evidence_item(
        citation_index=1,
        category_code="LAB_REPORT",
        chunk_index=0,
        content="Blood glucose is 110 mg/dL",
    )
    item2 = make_evidence_item(
        citation_index=2,
        category_code="PRESCRIPTION",
        chunk_index=1,
        content="Metformin 500mg daily",
    )
    context = make_assembled_context(
        items=(item1, item2),
        query="glucose and medications",
    )

    response_payload = GeminiAnswerPayload(
        answer="Patient has glucose 110 [1] and takes Metformin [2].",
        cited_indices=[1, 2],
    )
    client = MockGeminiClient(response=MockGenerateContentResponse(parsed=response_payload))
    generator = GeminiAnswerGenerator(client=client, model="gemini-3.8-flash")

    result = asyncio.run(generator.generate_answer(context))
    assert result is not None

    assert len(client.aio.models.calls) == 1
    prompt = client.aio.models.calls[0]["contents"]

    # Allowed fields are present
    assert "[1] Category: LAB_REPORT (Chunk: 0)" in prompt
    assert "Blood glucose is 110 mg/dL" in prompt
    assert "[2] Category: PRESCRIPTION (Chunk: 1)" in prompt
    assert "Metformin 500mg daily" in prompt
    assert "QUESTION:\nglucose and medications" in prompt


def test_prompt_excludes_internal_identifiers():
    rec_id = uuid4()
    patient_id = uuid4()
    item = make_evidence_item(
        citation_index=1,
        record_id=rec_id,
        content="Serum creatinine 0.9 mg/dL",
    )
    context = make_assembled_context(items=(item,), patient_id=patient_id)

    response_payload = GeminiAnswerPayload(
        answer="Creatinine is normal [1].",
        cited_indices=[1],
    )
    client = MockGeminiClient(response=MockGenerateContentResponse(parsed=response_payload))
    generator = GeminiAnswerGenerator(client=client)

    asyncio.run(generator.generate_answer(context))

    prompt = client.aio.models.calls[0]["contents"]

    assert str(patient_id) not in prompt
    assert str(rec_id) not in prompt
    assert str(item.chunk_id) not in prompt


def test_structured_response_maps_to_generated_answer():
    item = make_evidence_item(citation_index=1, category_code="LAB_REPORT")
    context = make_assembled_context(items=(item,))

    response_payload = GeminiAnswerPayload(
        answer="Glucose level is normal [1].",
        cited_indices=[1],
    )
    client = MockGeminiClient(response=MockGenerateContentResponse(parsed=response_payload))
    generator = GeminiAnswerGenerator(client=client, model="gemini-3.8-flash")

    result = asyncio.run(generator.generate_answer(context))

    assert result.answer == "Glucose level is normal [1]."
    assert len(result.citations) == 1
    assert result.provider == "gemini"
    assert result.model == "gemini-3.8-flash"


def test_citation_indices_map_to_context_provenance():
    rec_id_1 = uuid4()
    rec_id_2 = uuid4()
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
        chunk_index=3,
    )
    context = make_assembled_context(items=(item1, item2))

    response_payload = GeminiAnswerPayload(
        answer="Lab confirms condition [1], treated with meds [2].",
        cited_indices=[1, 2],
    )
    client = MockGeminiClient(response=MockGenerateContentResponse(parsed=response_payload))
    generator = GeminiAnswerGenerator(client=client)

    result = asyncio.run(generator.generate_answer(context))

    assert len(result.citations) == 2
    assert result.citations[0].citation_index == 1
    assert result.citations[0].record_id == rec_id_1
    assert result.citations[0].category_code == "LAB_REPORT"
    assert result.citations[0].chunk_index == 0

    assert result.citations[1].citation_index == 2
    assert result.citations[1].record_id == rec_id_2
    assert result.citations[1].category_code == "PRESCRIPTION"
    assert result.citations[1].chunk_index == 3


def test_invalid_citation_indices_are_ignored():
    rec_id = uuid4()
    item = make_evidence_item(citation_index=1, record_id=rec_id)
    context = make_assembled_context(items=(item,))

    # Model returned invalid/hallucinated citation indices 999 and -5
    response_payload = GeminiAnswerPayload(
        answer="Based on records [1] and [999].",
        cited_indices=[1, 999, -5],
    )
    client = MockGeminiClient(response=MockGenerateContentResponse(parsed=response_payload))
    generator = GeminiAnswerGenerator(client=client)

    result = asyncio.run(generator.generate_answer(context))

    assert len(result.citations) == 1
    assert result.citations[0].citation_index == 1
    assert result.citations[0].record_id == rec_id


def test_configured_model_is_forwarded_to_gemini():
    item = make_evidence_item(citation_index=1)
    context = make_assembled_context(items=(item,))

    response_payload = GeminiAnswerPayload(answer="Result", cited_indices=[1])
    client = MockGeminiClient(response=MockGenerateContentResponse(parsed=response_payload))
    generator = GeminiAnswerGenerator(client=client, model="gemini-custom-v2")

    asyncio.run(generator.generate_answer(context))

    assert client.aio.models.calls[0]["model"] == "gemini-custom-v2"


def test_gemini_api_error_is_normalized():
    class FakeAPIError(Exception):
        code = 429
        message = "Rate limit reached"

    item = make_evidence_item(citation_index=1)
    context = make_assembled_context(items=(item,))

    client = MockGeminiClient(side_effect=FakeAPIError("Rate limit reached"))
    generator = GeminiAnswerGenerator(client=client)

    with pytest.raises(GeminiRateLimitError, match="rate limit"):
        asyncio.run(generator.generate_answer(context))

    # Test 503 unavailable
    class FakeUnavailable(Exception):
        code = 503

    client_503 = MockGeminiClient(side_effect=FakeUnavailable("Server error"))
    generator_503 = GeminiAnswerGenerator(client=client_503)

    with pytest.raises(GeminiUnavailableError, match="unavailable"):
        asyncio.run(generator_503.generate_answer(context))


def test_gemini_safety_response_is_normalized():
    item = make_evidence_item(citation_index=1)
    context = make_assembled_context(items=(item,))

    safety_response = MockGenerateContentResponse(
        candidates=[MockCandidate(finish_reason="SAFETY")]
    )
    client = MockGeminiClient(response=safety_response)
    generator = GeminiAnswerGenerator(client=client)

    with pytest.raises(GeminiSafetyError, match="safety filters"):
        asyncio.run(generator.generate_answer(context))


def test_generated_answer_has_timezone_aware_timestamp():
    item = make_evidence_item(citation_index=1)
    context = make_assembled_context(items=(item,))

    response_payload = GeminiAnswerPayload(answer="Timestamp check [1]", cited_indices=[1])
    client = MockGeminiClient(response=MockGenerateContentResponse(parsed=response_payload))
    generator = GeminiAnswerGenerator(client=client)

    result = asyncio.run(generator.generate_answer(context))

    assert result.generated_at.tzinfo is not None
    assert result.generated_at.tzinfo == timezone.utc


def test_api_key_is_not_exposed_in_generated_answer():
    item = make_evidence_item(citation_index=1)
    context = make_assembled_context(items=(item,))

    secret_key = "super-secret-gemini-key-xyz"
    response_payload = GeminiAnswerPayload(answer="Result [1]", cited_indices=[1])
    client = MockGeminiClient(response=MockGenerateContentResponse(parsed=response_payload))
    generator = GeminiAnswerGenerator(client=client, api_key=secret_key)

    result = asyncio.run(generator.generate_answer(context))

    assert not hasattr(result, "api_key")
    assert secret_key not in str(result)
    assert secret_key not in repr(result)


def test_dependencies_provider_wiring():
    # Fake provider default
    fake_settings = Settings(ai_provider="fake")
    generator = get_answer_generator(fake_settings)
    assert isinstance(generator, FakeAnswerGenerator)

    # Gemini without key raises RuntimeError
    gemini_no_key_settings = Settings(ai_provider="gemini", gemini_api_key=None)
    with pytest.raises(RuntimeError, match="PULSEOS_GEMINI_API_KEY must be set"):
        get_answer_generator(gemini_no_key_settings)

    # Gemini with key returns GeminiAnswerGenerator
    gemini_settings = Settings(
        ai_provider="gemini",
        ai_model="gemini-3.8-flash",
        gemini_api_key="valid-test-key",
    )
    gemini_gen = get_answer_generator(gemini_settings)
    assert isinstance(gemini_gen, GeminiAnswerGenerator)
    assert gemini_gen.model == "gemini-3.8-flash"
    assert gemini_gen._timeout_seconds == 30.0

    # Overridden timeout in Settings propagates through dependency provider
    custom_timeout_settings = Settings(
        ai_provider="gemini",
        ai_model="gemini-3.8-flash",
        gemini_api_key="valid-test-key",
        gemini_timeout_seconds=45.0,
    )
    custom_gen = get_answer_generator(custom_timeout_settings)
    assert isinstance(custom_gen, GeminiAnswerGenerator)
    assert custom_gen._timeout_seconds == 45.0


def test_gemini_default_timeout_is_thirty_seconds() -> None:
    assert DEFAULT_GEMINI_TIMEOUT_SECONDS == 30.0
    client = MockGeminiClient()
    generator = GeminiAnswerGenerator(client=client)
    assert generator._timeout_seconds == 30.0


def test_gemini_timeout_can_be_overridden_in_constructor() -> None:
    client = MockGeminiClient()
    generator = GeminiAnswerGenerator(client=client, timeout_seconds=60.0)
    assert generator._timeout_seconds == 60.0


def test_gemini_timeout_raises_gemini_timeout_error() -> None:
    item = make_evidence_item(citation_index=1)
    context = make_assembled_context(items=(item,))

    client = MockGeminiClient(delay_seconds=1.0)
    generator = GeminiAnswerGenerator(client=client, timeout_seconds=0.02)

    with pytest.raises(GeminiTimeoutError, match="Gemini API request timed out.") as exc_info:
        asyncio.run(generator.generate_answer(context))

    assert isinstance(exc_info.value, GeminiTimeoutError)
    assert exc_info.value.__cause__ is None


def test_prompt_sanitizes_health_id_and_phone():
    item = make_evidence_item(
        citation_index=1,
        category_code="LAB_REPORT",
        chunk_index=0,
        content="Blood glucose is 110 mg/dL",
    )
    context = make_assembled_context(
        items=(item,),
        query="Show records for PHI-IND-2026-ABC123XYZ or call +919876543210",
    )

    response_payload = GeminiAnswerPayload(
        answer="Fasting blood glucose is 110 mg/dL [1].",
        cited_indices=[1],
    )
    client = MockGeminiClient(response=MockGenerateContentResponse(parsed=response_payload))
    generator = GeminiAnswerGenerator(client=client)

    result = asyncio.run(generator.generate_answer(context))
    assert result.answer == "Fasting blood glucose is 110 mg/dL [1]."

    assert len(client.aio.models.calls) == 1
    prompt = client.aio.models.calls[0]["contents"]

    # Direct identifiers replaced in prompt
    assert "[HEALTH_ID]" in prompt
    assert "[PHONE]" in prompt
    assert "PHI-IND-2026-ABC123XYZ" not in prompt
    assert "+919876543210" not in prompt

    # Clinical evidence is untouched
    assert "Blood glucose is 110 mg/dL" in prompt

    # Original context object is NOT mutated
    assert context.query == "Show records for PHI-IND-2026-ABC123XYZ or call +919876543210"
    assert context.items[0].content == "Blood glucose is 110 mg/dL"


def test_gemini_client_configured_with_bounded_retries() -> None:
    generator = GeminiAnswerGenerator(api_key="test-api-key-offline")
    client = generator._client
    assert hasattr(client, "_api_client")
    retry_options = client._api_client._http_options.retry_options
    assert retry_options is not None
    assert retry_options.attempts == 3
    assert client._api_client._async_retry.stop.max_attempt_number == 3


def test_format_gemini_prompt_clinician_remains_unchanged():
    item1 = make_evidence_item(
        citation_index=1,
        category_code="LAB_REPORT",
        chunk_index=0,
        content="Fasting glucose is 105 mg/dL",
    )
    item2 = make_evidence_item(
        citation_index=2,
        category_code="DISCHARGE_SUMMARY",
        chunk_index=1,
        content="Patient was discharged in stable condition.",
    )
    context = make_assembled_context(
        items=(item1, item2),
        query="What is the fasting glucose level?",
        audience=ContextAudience.CLINICIAN,
    )

    prompt = format_gemini_prompt(context)

    # Clinician prompt characteristics
    assert "SYSTEM:\nYou are a clinical information retrieval and synthesis assistant." in prompt
    assert "- Use only the provided evidence." in prompt
    assert "- Do not invent or infer unsupported clinical facts." in prompt
    assert "- Every clinical factual statement must cite evidence using [n]." in prompt
    assert '  "The available medical records do not contain information regarding the requested topic."' in prompt
    assert "- Do not provide an autonomous diagnosis or medical advice." in prompt
    assert "EVIDENCE:\n\n[1] Category: LAB_REPORT (Chunk: 0)\nContent: Fasting glucose is 105 mg/dL\n\n[2] Category: DISCHARGE_SUMMARY (Chunk: 1)\nContent: Patient was discharged in stable condition." in prompt
    assert "QUESTION:\nWhat is the fasting glucose level?" in prompt
    # Clinician prompt does NOT contain patient copilot phrasing
    assert "PulseOS Health Copilot" not in prompt
    assert "PATIENT SAFETY / COMMUNICATION RULES:" not in prompt


def test_format_patient_copilot_prompt_contains_all_safety_rules():
    item = make_evidence_item(
        citation_index=1,
        category_code="LAB_REPORT",
        chunk_index=0,
        content="Blood glucose is 110 mg/dL",
    )
    context = make_assembled_context(
        items=(item,),
        query="What is my blood sugar?",
        audience=ContextAudience.PATIENT,
    )

    prompt = format_patient_copilot_prompt(context)

    # System header
    assert "SYSTEM:\nYou are PulseOS Health Copilot, an AI assistant helping patients understand their medical records." in prompt
    assert "PATIENT SAFETY / COMMUNICATION RULES:" in prompt

    # All required safety / communication rules
    assert "1. Use ONLY the provided medical-record evidence." in prompt
    assert "2. Never invent, assume, or extrapolate facts not present in the evidence." in prompt
    assert "3. Explain documented medical information in clear, plain language." in prompt
    assert "4. Use an empathetic, respectful, non-alarming tone." in prompt
    assert "5. Clearly distinguish documented facts from general educational explanations of medical terms." in prompt
    assert "6. Every statement referring to a medical fact from the records MUST cite the relevant evidence using [n]." in prompt
    assert "7. NEVER diagnose the patient." in prompt
    assert "8. NEVER speculate about conditions that are not documented in the evidence." in prompt
    assert "9. NEVER prescribe medication." in prompt
    assert "10. NEVER recommend changing, increasing, decreasing, or stopping medication." in prompt
    assert "11. NEVER provide a treatment plan." in prompt
    assert '12. If the provided evidence does not answer the patient\'s question, say exactly:\n   "The available medical records do not contain information regarding the requested topic."' in prompt
    assert "13. For medical decisions, diagnosis, treatment, or medication changes, explicitly encourage the patient to consult their doctor or clinical team." in prompt

    # Evidence block and patient question
    assert "EVIDENCE:\n\n[1] Category: LAB_REPORT (Chunk: 0)\nContent: Blood glucose is 110 mg/dL" in prompt
    assert "PATIENT QUESTION:\nWhat is my blood sugar?" in prompt


def test_patient_prompt_uses_sanitized_query_redacting_identifiers():
    item = make_evidence_item(
        citation_index=1,
        category_code="LAB_REPORT",
        chunk_index=0,
        content="Blood glucose is 110 mg/dL",
    )
    context = make_assembled_context(
        items=(item,),
        query="Explain results for PHI-IND-2026-XYZ987 or SMS me at +919876543210",
        audience=ContextAudience.PATIENT,
    )

    prompt = format_patient_copilot_prompt(context)

    # Identifiers redacted
    assert "[HEALTH_ID]" in prompt
    assert "[PHONE]" in prompt
    assert "PHI-IND-2026-XYZ987" not in prompt
    assert "+919876543210" not in prompt

    # Question label and sanitized query present
    assert "PATIENT QUESTION:\nExplain results for [HEALTH_ID] or SMS me at [PHONE]" in prompt

    # Original query intact on context
    assert context.query == "Explain results for PHI-IND-2026-XYZ987 or SMS me at +919876543210"


def test_patient_prompt_does_not_leak_internal_identifiers():
    patient_id = uuid4()
    record_id = uuid4()
    chunk_id = uuid4()

    item = ContextEvidenceItem(
        chunk_id=chunk_id,
        record_id=record_id,
        category_code="PRESCRIPTION",
        chunk_index=0,
        content="Metformin 500mg once daily with meals.",
        token_count=15,
        citation_index=1,
    )
    context = make_assembled_context(
        items=(item,),
        query="What is my medication schedule?",
        patient_id=patient_id,
        audience=ContextAudience.PATIENT,
    )

    prompt = format_patient_copilot_prompt(context)

    # Model-facing prompt must NEVER contain UUIDs or internal IDs
    assert str(patient_id) not in prompt
    assert str(record_id) not in prompt
    assert str(chunk_id) not in prompt

    # Permitted fields ONLY
    assert "[1] Category: PRESCRIPTION (Chunk: 0)" in prompt
    assert "Content: Metformin 500mg once daily with meals." in prompt


def test_generator_dispatches_patient_prompt_when_audience_is_patient():
    item = make_evidence_item(
        citation_index=1,
        category_code="LAB_REPORT",
        chunk_index=0,
        content="HbA1c is 5.6%",
    )
    context = make_assembled_context(
        items=(item,),
        query="What does my HbA1c mean?",
        audience=ContextAudience.PATIENT,
    )

    response_payload = GeminiAnswerPayload(
        answer="Your HbA1c is 5.6%, which is within normal range [1].",
        cited_indices=[1],
    )
    client = MockGeminiClient(response=MockGenerateContentResponse(parsed=response_payload))
    generator = GeminiAnswerGenerator(client=client)

    result = asyncio.run(generator.generate_answer(context))
    assert result.answer == "Your HbA1c is 5.6%, which is within normal range [1]."

    assert len(client.aio.models.calls) == 1
    sent_contents = client.aio.models.calls[0]["contents"]

    # Verify Patient prompt was dispatched
    assert "You are PulseOS Health Copilot" in sent_contents
    assert "PATIENT SAFETY / COMMUNICATION RULES:" in sent_contents
    assert "PATIENT QUESTION:\nWhat does my HbA1c mean?" in sent_contents
    # Verify Clinician prompt header was NOT used
    assert "You are a clinical information retrieval and synthesis assistant." not in sent_contents


def test_generator_dispatches_clinician_prompt_when_audience_is_clinician():
    item = make_evidence_item(
        citation_index=1,
        category_code="LAB_REPORT",
        chunk_index=0,
        content="HbA1c is 5.6%",
    )
    context = make_assembled_context(
        items=(item,),
        query="Evaluate HbA1c trend",
        audience=ContextAudience.CLINICIAN,
    )

    response_payload = GeminiAnswerPayload(
        answer="HbA1c documented at 5.6% [1].",
        cited_indices=[1],
    )
    client = MockGeminiClient(response=MockGenerateContentResponse(parsed=response_payload))
    generator = GeminiAnswerGenerator(client=client)

    result = asyncio.run(generator.generate_answer(context))
    assert result.answer == "HbA1c documented at 5.6% [1]."

    assert len(client.aio.models.calls) == 1
    sent_contents = client.aio.models.calls[0]["contents"]

    # Verify Clinician prompt was dispatched
    assert "You are a clinical information retrieval and synthesis assistant." in sent_contents
    assert "QUESTION:\nEvaluate HbA1c trend" in sent_contents
    # Verify Patient prompt header was NOT used
    assert "You are PulseOS Health Copilot" not in sent_contents
    assert "PATIENT SAFETY / COMMUNICATION RULES:" not in sent_contents



