"""Tests for modular Ollama AnswerGenerator provider adapter."""

import asyncio
import json
from datetime import UTC, date
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from app.core.config import Settings
from app.modules.ai.context import AssembledContext, ContextAudience, ContextEvidenceItem
from app.modules.ai.dependencies import get_answer_generator, to_http_error
from app.modules.ai.generation import AnswerGenerator, FakeAnswerGenerator, GeneratedAnswer
from app.modules.ai.providers.ollama import (
    DEFAULT_OLLAMA_MODEL,
    EMPTY_EVIDENCE_ANSWER,
    OLLAMA_ANSWER_SCHEMA,
    OllamaAnswerGenerator,
    OllamaProviderError,
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)


def make_evidence_item(
    *,
    citation_index: int = 1,
    record_id: UUID | None = None,
    chunk_id: UUID | None = None,
    category_code: str = "LAB_REPORT",
    chunk_index: int = 0,
    content: str = "Fasting glucose is 105 mg/dL",
    token_count: int = 20,
    date_of_service: date | None = None,
) -> ContextEvidenceItem:
    return ContextEvidenceItem(
        chunk_id=chunk_id or uuid4(),
        record_id=record_id or uuid4(),
        category_code=category_code,
        chunk_index=chunk_index,
        content=content,
        token_count=token_count,
        citation_index=citation_index,
        date_of_service=date_of_service,
    )


def make_assembled_context(
    items: tuple[ContextEvidenceItem, ...] = (),
    *,
    query: str = "What is the patient's glucose level?",
    patient_id: UUID | None = None,
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


def make_mock_client(
    handler: Any,
    base_url: str = "http://localhost:11434",
) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, base_url=base_url)


def test_ollama_provider_implements_answer_generator() -> None:
    generator = OllamaAnswerGenerator()
    assert isinstance(generator, AnswerGenerator)


def test_successful_generation() -> None:
    recorded_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        response_body = {
            "model": "qwen3:8b",
            "message": {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "answer": "The patient's fasting blood glucose is 105 mg/dL [1].",
                        "cited_indices": [1],
                    }
                ),
            },
            "done": True,
        }
        return httpx.Response(200, json=response_body)

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)

    item = make_evidence_item(citation_index=1, content="Fasting blood glucose: 105 mg/dL")
    context = make_assembled_context(items=(item,))

    result = asyncio.run(generator.generate_answer(context))

    assert isinstance(result, GeneratedAnswer)
    assert result.provider == "ollama"
    assert result.model == "qwen3:8b"
    assert result.answer == "The patient's fasting blood glucose is 105 mg/dL [1]."
    assert len(result.citations) == 1
    assert result.citations[0].citation_index == 1
    assert result.citations[0].record_id == item.record_id
    assert result.citations[0].category_code == "LAB_REPORT"
    assert result.citations[0].chunk_index == 0
    assert result.generated_at.tzinfo == UTC
    assert len(recorded_requests) == 1

    # Verify request payload disables thinking and enforces required settings
    payload = json.loads(recorded_requests[0].content)
    assert payload["think"] is False
    assert payload["stream"] is False
    assert payload["options"]["temperature"] == 0.0
    assert payload["format"] == OLLAMA_ANSWER_SCHEMA


def test_request_payload_parameters_and_think_disabled() -> None:
    captured_payload: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"answer": "Answer [1].", "cited_indices": [1]}),
                }
            },
        )

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)

    item = make_evidence_item(citation_index=1, content="Glucose 100")
    context = make_assembled_context(items=(item,))

    asyncio.run(generator.generate_answer(context))

    assert captured_payload["think"] is False
    assert captured_payload["stream"] is False
    assert captured_payload["options"]["temperature"] == 0.0
    assert captured_payload["format"] == OLLAMA_ANSWER_SCHEMA
    assert captured_payload["model"] == "qwen3:8b"


def test_citation_extraction_multiple_items() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        response_body = {
            "model": "qwen3:8b",
            "message": {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "answer": "Hypertension noted in [1] and confirmed in [3].",
                        "cited_indices": [1, 3],
                    }
                ),
            },
            "done": True,
        }
        return httpx.Response(200, json=response_body)

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)

    item1 = make_evidence_item(citation_index=1, content="BP 140/90")
    item2 = make_evidence_item(citation_index=2, content="Heart rate 72 bpm")
    item3 = make_evidence_item(citation_index=3, content="Prior hypertension history")
    context = make_assembled_context(items=(item1, item2, item3))

    result = asyncio.run(generator.generate_answer(context))

    assert len(result.citations) == 2
    assert result.citations[0].citation_index == 1
    assert result.citations[0].record_id == item1.record_id
    assert result.citations[1].citation_index == 3
    assert result.citations[1].record_id == item3.record_id


def test_invalid_citation_indices_ignored_without_crashing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        response_body = {
            "model": "qwen3:8b",
            "message": {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "answer": "Documented finding [1].",
                        "cited_indices": [1, 999, -4, 0, 42],
                    }
                ),
            },
            "done": True,
        }
        return httpx.Response(200, json=response_body)

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)

    item = make_evidence_item(citation_index=1, content="Single evidence chunk")
    context = make_assembled_context(items=(item,))

    result = asyncio.run(generator.generate_answer(context))

    assert len(result.citations) == 1
    assert result.citations[0].citation_index == 1


def test_empty_evidence_makes_zero_http_calls() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={})

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)

    context = make_assembled_context(items=())
    result = asyncio.run(generator.generate_answer(context))

    assert call_count == 0
    assert result.answer == EMPTY_EVIDENCE_ANSWER
    assert result.citations == ()
    assert result.provider == "ollama"
    assert result.model == DEFAULT_OLLAMA_MODEL


def test_clinician_prompt_structure() -> None:
    captured_payload: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "answer": "Clinical synthesis [1].",
                            "cited_indices": [1],
                        }
                    ),
                }
            },
        )

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)

    item = make_evidence_item(citation_index=1, content="Serum sodium: 140 mEq/L")
    context = make_assembled_context(
        items=(item,),
        query="What is the sodium level?",
        audience=ContextAudience.CLINICIAN,
    )

    asyncio.run(generator.generate_answer(context))

    messages = captured_payload["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    system_text = messages[0]["content"]

    # Safety rules
    assert "clinical information retrieval and synthesis assistant" in system_text
    assert "Use only the provided evidence." in system_text
    assert "Do not invent or infer unsupported clinical facts." in system_text
    assert "Do not provide an autonomous diagnosis or medical advice." in system_text

    # Tightened citation formatting rules
    assert "exact citation markers like [1], [2], [3]" in system_text
    assert (
        "Citation numbers must correspond to the supplied evidence citation indices." in system_text
    )
    assert "Never output [n1], [n2], [citation1], etc." in system_text
    assert "Do not invent citation numbers." in system_text
    assert "Do not use citation formats other than [N]." in system_text

    user_text = messages[1]["content"]
    assert "EVIDENCE:" in user_text
    assert "[1] Category: LAB_REPORT" in user_text
    assert "QUESTION:\nWhat is the sodium level?" in user_text
    assert captured_payload["think"] is False
    assert captured_payload["stream"] is False
    assert captured_payload["options"]["temperature"] == 0.0


def test_patient_prompt_structure() -> None:
    captured_payload: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "answer": "Your test shows normal sodium [1].",
                            "cited_indices": [1],
                        }
                    ),
                }
            },
        )

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)

    item = make_evidence_item(citation_index=1, content="Serum sodium: 140 mEq/L")
    context = make_assembled_context(
        items=(item,),
        query="Is my sodium normal?",
        audience=ContextAudience.PATIENT,
    )

    asyncio.run(generator.generate_answer(context))

    messages = captured_payload["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    system_text = messages[0]["content"]

    # Safety rules
    assert "PulseOS Health Copilot" in system_text
    assert "plain language" in system_text
    assert "empathetic, respectful, non-alarming tone" in system_text
    assert "NEVER diagnose the patient" in system_text
    assert "NEVER speculate about conditions" in system_text
    assert "NEVER prescribe medication" in system_text
    assert "consult their doctor or clinical team" in system_text

    # Tightened citation formatting rules
    assert "exact citation markers like [1], [2], [3]" in system_text
    assert (
        "Citation numbers must correspond to the supplied evidence citation indices." in system_text
    )
    assert "Never output [n1], [n2], [citation1], etc." in system_text
    assert "Do not invent citation numbers." in system_text
    assert "Do not use citation formats other than [N]." in system_text

    # Completeness rules at the end
    assert "21. Provide a complete answer that thoroughly addresses the question." in system_text
    assert "22. Do not stop at an introductory heading or sentence." in system_text
    assert (
        "23. Fully enumerate all requested findings and clinical details supported by the evidence."
        in system_text
    )
    assert (
        "24. When asked to list or summarize medications, conditions, or findings,"
        " explicitly state each supported item and its status in the answer text,"
        " citing the supporting evidence."
        in system_text
    )
    assert (
        "25. Do not treat cited_indices alone as a substitute for answering the"
        " question in the answer field."
        in system_text
    )
    assert "26. Do not add unsupported items to make an answer appear complete." in system_text
    assert system_text.index(
        "consult their doctor or clinical team"
    ) < system_text.index("21. Provide a complete answer")

    user_text = messages[1]["content"]
    assert "EVIDENCE:" in user_text
    assert "PATIENT QUESTION:\nIs my sodium normal?" in user_text
    assert captured_payload["think"] is False


def test_outbound_prompt_does_not_contain_phi_or_internal_metadata() -> None:
    captured_payload: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "answer": "Test answer [1].",
                            "cited_indices": [1],
                        }
                    ),
                }
            },
        )

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)

    secret_patient_id = uuid4()
    secret_record_id = uuid4()
    secret_chunk_id = uuid4()

    item = make_evidence_item(
        citation_index=1,
        record_id=secret_record_id,
        chunk_id=secret_chunk_id,
        content="Evidence content only",
    )
    context = make_assembled_context(
        items=(item,),
        patient_id=secret_patient_id,
    )

    asyncio.run(generator.generate_answer(context))

    raw_body = json.dumps(captured_payload)

    # Must NOT leak IDs or metadata keys
    assert str(secret_patient_id) not in raw_body
    assert str(secret_record_id) not in raw_body
    assert str(secret_chunk_id) not in raw_body
    assert "patient_id" not in raw_body
    assert "record_id" not in raw_body
    assert "chunk_id" not in raw_body
    assert "document_id" not in raw_body
    assert "category_id" not in raw_body
    assert "firebase_uid" not in raw_body.lower()
    assert "consent" not in raw_body.lower()
    assert "audit" not in raw_body.lower()
    assert "storage_key" not in raw_body.lower()
    assert "score" not in raw_body.lower()


def test_connection_failure_maps_to_ollama_unavailable_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused by localhost:11434")

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)
    context = make_assembled_context(items=(make_evidence_item(),))

    with pytest.raises(OllamaUnavailableError, match="unavailable"):
        asyncio.run(generator.generate_answer(context))


def test_timeout_maps_to_ollama_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Request timed out after 60s")

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)
    context = make_assembled_context(items=(make_evidence_item(),))

    with pytest.raises(OllamaTimeoutError, match="timed out"):
        asyncio.run(generator.generate_answer(context))


def test_http_503_maps_to_ollama_unavailable_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)
    context = make_assembled_context(items=(make_evidence_item(),))

    with pytest.raises(OllamaUnavailableError):
        asyncio.run(generator.generate_answer(context))


def test_http_504_maps_to_ollama_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(504, text="Gateway Timeout")

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)
    context = make_assembled_context(items=(make_evidence_item(),))

    with pytest.raises(OllamaTimeoutError):
        asyncio.run(generator.generate_answer(context))


def test_malformed_json_response_maps_to_ollama_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Internal Error Occurred")

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)
    context = make_assembled_context(items=(make_evidence_item(),))

    with pytest.raises(OllamaResponseError):
        asyncio.run(generator.generate_answer(context))


def test_malformed_content_json_maps_to_ollama_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "not-a-valid-json{"}},
        )

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)
    context = make_assembled_context(items=(make_evidence_item(),))

    with pytest.raises(OllamaResponseError):
        asyncio.run(generator.generate_answer(context))


def test_schema_mismatch_maps_to_ollama_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"unknown_field": 123}),
                }
            },
        )

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)
    context = make_assembled_context(items=(make_evidence_item(),))

    with pytest.raises(OllamaResponseError):
        asyncio.run(generator.generate_answer(context))


def test_empty_content_maps_to_ollama_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": ""}},
        )

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)
    context = make_assembled_context(items=(make_evidence_item(),))

    with pytest.raises(OllamaResponseError):
        asyncio.run(generator.generate_answer(context))


def test_empty_answer_field_maps_to_ollama_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"answer": "   ", "cited_indices": []}),
                }
            },
        )

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)
    context = make_assembled_context(items=(make_evidence_item(),))

    with pytest.raises(OllamaResponseError):
        asyncio.run(generator.generate_answer(context))


def test_markdown_code_fenced_json_is_parsed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        fenced_json = (
            "```json\n"
            + json.dumps(
                {
                    "answer": "Fenced answer [1].",
                    "cited_indices": [1],
                }
            )
            + "\n```"
        )
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": fenced_json}},
        )

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)
    context = make_assembled_context(items=(make_evidence_item(),))

    result = asyncio.run(generator.generate_answer(context))
    assert result.answer == "Fenced answer [1]."
    assert len(result.citations) == 1


def test_configured_model_base_url_and_timeout() -> None:
    recorded_url: str = ""
    recorded_model: str = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal recorded_url, recorded_model
        recorded_url = str(request.url)
        payload = json.loads(request.content)
        recorded_model = payload.get("model", "")
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "answer": "Custom provider answer [1].",
                            "cited_indices": [1],
                        }
                    ),
                }
            },
        )

    custom_url = "http://custom-ollama:11434"
    client = make_mock_client(handler, base_url=custom_url)
    generator = OllamaAnswerGenerator(
        base_url=custom_url,
        model="qwen3:8b",
        timeout_seconds=45.0,
        client=client,
    )

    assert generator.base_url == custom_url
    assert generator.model == "qwen3:8b"
    assert generator.timeout_seconds == 45.0

    context = make_assembled_context(items=(make_evidence_item(),))
    asyncio.run(generator.generate_answer(context))

    assert recorded_url == "http://custom-ollama:11434/api/chat"
    assert recorded_model == "qwen3:8b"


def test_dependency_wiring_for_ai_provider_ollama() -> None:
    settings = Settings(
        ai_provider="ollama",
        ollama_base_url="http://local-test:11434",
        ollama_model="qwen3:8b",
        ollama_timeout_seconds=50.0,
    )
    generator = get_answer_generator(settings)

    assert isinstance(generator, OllamaAnswerGenerator)
    assert generator.base_url == "http://local-test:11434"
    assert generator.model == "qwen3:8b"
    assert generator.timeout_seconds == 50.0


def test_dependency_wiring_for_ai_provider_fake() -> None:
    settings = Settings(ai_provider="fake")
    generator = get_answer_generator(settings)
    assert isinstance(generator, FakeAnswerGenerator)


def test_dependency_wiring_default_is_ollama() -> None:
    settings = Settings()
    generator = get_answer_generator(settings)
    assert isinstance(generator, OllamaAnswerGenerator)


def test_to_http_error_mappings_for_ollama() -> None:
    timeout_err = OllamaTimeoutError("Timed out")
    http_err_timeout = to_http_error(timeout_err)
    assert http_err_timeout.status_code == 504
    assert http_err_timeout.detail == "Local AI answer generation timed out."

    unavailable_err = OllamaUnavailableError("Unavailable")
    http_err_unavailable = to_http_error(unavailable_err)
    assert http_err_unavailable.status_code == 503
    assert (
        http_err_unavailable.detail
        == "Local AI service (Ollama) is unavailable. Please ensure Ollama is running."
    )

    resp_err = OllamaResponseError("Invalid JSON")
    http_err_resp = to_http_error(resp_err)
    assert http_err_resp.status_code == 502
    assert http_err_resp.detail == "Local AI service returned an invalid response."

    provider_err = OllamaProviderError("Generic failure")
    http_err_provider = to_http_error(provider_err)
    assert http_err_provider.status_code == 502
    assert http_err_provider.detail == "Local AI operation failed."


def test_t8_ollama_evidence_headers_contain_individual_verified_dates() -> None:
    captured_payload: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "answer": "Both panels reviewed [1], [2].",
                        "cited_indices": [1, 2],
                    }),
                }
            },
        )

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)

    item1 = make_evidence_item(
        citation_index=1,
        category_code="LAB_REPORT",
        content="BMP values",
        date_of_service=date(2018, 10, 1),
    )
    item2 = make_evidence_item(
        citation_index=2,
        category_code="LAB_REPORT",
        content="Lipid panel values",
        date_of_service=date(2017, 9, 24),
    )

    context = make_assembled_context(items=(item1, item2))
    asyncio.run(generator.generate_answer(context))

    user_text = captured_payload["messages"][1]["content"]

    # Each evidence block has its own structured date in the header
    assert "[1] Category: LAB_REPORT | Date: 2018-10-01 | Chunk: 0" in user_text
    assert "[2] Category: LAB_REPORT | Date: 2017-09-24 | Chunk: 0" in user_text


def test_t9_missing_date_evidence_header_marks_unrecorded() -> None:
    captured_payload: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"answer": "Report [1].", "cited_indices": [1]}),
                }
            },
        )

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)

    item = make_evidence_item(
        citation_index=1,
        category_code="PROCEDURE",
        content="Colonoscopy completed",
        date_of_service=None,
    )

    context = make_assembled_context(items=(item,))
    asyncio.run(generator.generate_answer(context))

    user_text = captured_payload["messages"][1]["content"]

    # Undated item must specify "Date: unrecorded" without fabricating a date
    assert "[1] Category: PROCEDURE | Date: unrecorded | Chunk: 0" in user_text


def test_t10_clinician_prompt_contains_anti_date_conflation_rules() -> None:
    captured_payload: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"answer": "Report [1].", "cited_indices": [1]}),
                }
            },
        )

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)

    item = make_evidence_item()
    context = make_assembled_context(items=(item,))
    asyncio.run(generator.generate_answer(context))

    system_text = captured_payload["messages"][0]["content"]

    # Explicit anti-date-conflation and independent grounding instructions
    assert (
        "Use only the date in the evidence block associated with the cited record."
        in system_text
    )
    assert "Never copy a date from another evidence block." in system_text
    assert (
        "If the evidence has no date or is unrecorded, state that the date is unrecorded."
        in system_text
    )
    assert (
        "Do not infer which record is newer unless its dates support that claim."
        in system_text
    )

    # Completeness rules at the end
    assert (
        "- Provide a complete answer that thoroughly addresses the question."
        in system_text
    )
    assert "- Do not stop at an introductory heading or sentence." in system_text
    assert (
        "- Fully enumerate all requested findings and clinical details supported"
        " by the evidence."
        in system_text
    )
    assert (
        "- When asked to list or summarize medications, conditions, or findings,"
        " explicitly state each supported item and its status in the answer text,"
        " citing the supporting evidence."
        in system_text
    )
    assert (
        "- Do not treat cited_indices alone as a substitute for answering the"
        " question in the answer field."
        in system_text
    )
    assert (
        "- Do not add unsupported items to make an answer appear complete."
        in system_text
    )
    assert system_text.index(
        "Do not provide an autonomous diagnosis or medical advice."
    ) < system_text.index("- Provide a complete answer")


def test_medication_context_complete_structured_response_handling() -> None:
    captured_payload: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.content)
        answer_text = (
            "The available medical records list the following medications:\n"
            "1. Simvastatin 10 MG: Active [1] (2018-09-24), Stopped [2] (2017-09-24)\n"
            "2. Ibuprofen 200 MG Oral Tablet: Stopped [3] (2016-09-12)"
        )
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "answer": answer_text,
                        "cited_indices": [1, 2, 3],
                    }),
                }
            },
        )

    client = make_mock_client(handler)
    generator = OllamaAnswerGenerator(client=client)

    item1 = make_evidence_item(
        citation_index=1,
        category_code="PRESCRIPTION",
        date_of_service=date(2018, 9, 24),
        content="Medication: Simvastatin 10 MG Status: active",
    )
    item2 = make_evidence_item(
        citation_index=2,
        category_code="PRESCRIPTION",
        date_of_service=date(2017, 9, 24),
        content="Medication: Simvastatin 10 MG Status: stopped",
    )
    item3 = make_evidence_item(
        citation_index=3,
        category_code="PRESCRIPTION",
        date_of_service=date(2016, 9, 12),
        content="Medication: Ibuprofen 200 MG Status: stopped",
    )
    context = make_assembled_context(
        items=(item1, item2, item3),
        query="Which medications are listed in the records, and which are active versus stopped?",
    )

    result = asyncio.run(generator.generate_answer(context))

    assert "Simvastatin 10 MG: Active [1]" in result.answer
    assert "Ibuprofen 200 MG Oral Tablet: Stopped [3]" in result.answer
    assert len(result.citations) == 3
    assert result.citations[0].record_id == item1.record_id
    assert result.citations[0].category_code == "PRESCRIPTION"
    assert result.citations[1].record_id == item2.record_id
    assert result.citations[2].record_id == item3.record_id
