"""Ollama local AI answer generation provider adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Final

import httpx
from pydantic import BaseModel, Field

from app.modules.ai.context import AssembledContext, ContextAudience
from app.modules.ai.generation import (
    CitationReference,
    GeneratedAnswer,
)
from app.modules.ai.text import sanitize_clinical_query

DEFAULT_OLLAMA_BASE_URL: Final[str] = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL: Final[str] = "qwen3:8b"
DEFAULT_OLLAMA_TIMEOUT_SECONDS: Final[float] = 60.0

EMPTY_EVIDENCE_ANSWER: Final[str] = (
    "The available medical records do not contain information regarding the requested topic."
)

OLLAMA_ANSWER_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "cited_indices": {
            "type": "array",
            "items": {"type": "integer"},
        },
    },
    "required": ["answer", "cited_indices"],
}


class OllamaProviderError(Exception):
    """Base exception for Ollama provider errors."""


class OllamaUnavailableError(OllamaProviderError):
    """Ollama service is unreachable, down, or connection refused."""


class OllamaTimeoutError(OllamaProviderError):
    """Ollama request timed out."""


class OllamaResponseError(OllamaProviderError):
    """Ollama returned an invalid, empty, or malformed response."""


class OllamaAnswerPayload(BaseModel):
    """Provider-local structured response payload from Ollama."""

    answer: str = Field(
        description=(
            "The synthesized clinical answer citing sources using bracketed notation like [1], [2]."
        )
    )
    cited_indices: list[int] = Field(
        default_factory=list,
        description="List of 1-based citation indices cited in the answer.",
    )


def format_ollama_clinician_system_prompt() -> str:
    """Format clinician synthesis system prompt."""
    return (
        "You are a clinical information retrieval and synthesis assistant.\n\n"
        "Rules:\n"
        "- Use only the provided evidence.\n"
        "- Do not invent or infer unsupported clinical facts.\n"
        "- Every clinical factual statement must cite evidence using exact citation"
        " markers like [1], [2], [3].\n"
        "- Citation numbers must correspond to the supplied evidence citation indices.\n"
        "- Use only the date in the evidence block associated with the cited record.\n"
        "- Never copy a date from another evidence block.\n"
        "- If the evidence has no date or is unrecorded, state that the date is unrecorded.\n"
        "- Do not infer which record is newer unless its dates support that claim.\n"
        "- Never output [n1], [n2], [citation1], etc.\n"
        "- Do not invent citation numbers.\n"
        "- Do not use citation formats other than [N].\n"
        "- If the evidence does not answer the question, say:\n"
        '  "The available medical records do not contain information regarding the'
        ' requested topic."\n'
        "- Do not provide an autonomous diagnosis or medical advice.\n"
        "- Provide a complete answer that thoroughly addresses the question.\n"
        "- Do not stop at an introductory heading or sentence.\n"
        "- Fully enumerate all requested findings and clinical details supported"
        " by the evidence.\n"
        "- When asked to list or summarize medications, conditions, or findings,"
        " explicitly state each supported item and its status in the answer"
        " text, citing the supporting evidence.\n"
        "- Do not treat cited_indices alone as a substitute for answering the"
        " question in the answer field.\n"
        "- Do not add unsupported items to make an answer appear complete."
    )


def format_ollama_patient_system_prompt() -> str:
    """Format patient Health Copilot system prompt."""
    return (
        "You are PulseOS Health Copilot, an AI assistant helping patients"
        " understand their medical records.\n\n"
        "PATIENT SAFETY / COMMUNICATION RULES:\n\n"
        "1. Use ONLY the provided medical-record evidence.\n"
        "2. Never invent, assume, or extrapolate facts not present in the evidence.\n"
        "3. Explain documented medical information in clear, plain language.\n"
        "4. Use an empathetic, respectful, non-alarming tone.\n"
        "5. Clearly distinguish documented facts from general educational explanations"
        " of medical terms.\n"
        "6. Every statement referring to a medical fact from the records MUST cite"
        " the relevant evidence using exact citation markers like [1], [2], [3].\n"
        "7. Citation numbers must correspond to the supplied evidence citation indices.\n"
        "8. Use only the date in the evidence block associated with the cited record;\n"
        "   never copy a date from another evidence block.\n"
        "9. If the evidence has no date or is unrecorded, state that the date is unrecorded.\n"
        "10. Do not infer which record is newer unless its dates support that claim.\n"
        "11. Never output [n1], [n2], [citation1], etc.\n"
        "12. Do not invent citation numbers.\n"
        "13. Do not use citation formats other than [N].\n"
        "14. NEVER diagnose the patient.\n"
        "15. NEVER speculate about conditions that are not documented in the evidence.\n"
        "16. NEVER prescribe medication.\n"
        "17. NEVER recommend changing, increasing, decreasing, or stopping medication.\n"
        "18. NEVER provide a treatment plan.\n"
        "19. If the provided evidence does not answer the patient's question, say exactly:\n"
        '   "The available medical records do not contain information regarding the'
        ' requested topic."\n'
        "20. For medical decisions, diagnosis, treatment, or medication changes,"
        " explicitly encourage the patient to consult their doctor or clinical team.\n"
        "21. Provide a complete answer that thoroughly addresses the question.\n"
        "22. Do not stop at an introductory heading or sentence.\n"
        "23. Fully enumerate all requested findings and clinical details supported"
        " by the evidence.\n"
        "24. When asked to list or summarize medications, conditions, or findings,"
        " explicitly state each supported item and its status in the answer"
        " text, citing the supporting evidence.\n"
        "25. Do not treat cited_indices alone as a substitute for answering the"
        " question in the answer field.\n"
        "26. Do not add unsupported items to make an answer appear complete."
    )


def format_ollama_user_message(context: AssembledContext) -> str:
    """Format user message strictly containing allowed evidence and sanitized query."""
    evidence_blocks: list[str] = []
    for item in context.items:
        date_str = (
            item.date_of_service.isoformat()
            if item.date_of_service is not None
            else "unrecorded"
        )
        header = (
            f"[{item.citation_index}] Category: {item.category_code} "
            f"| Date: {date_str} | Chunk: {item.chunk_index}"
        )
        evidence_blocks.append(f"{header}\nContent: {item.content}")

    evidence_text = "\n\n".join(evidence_blocks)
    sanitized_query = sanitize_clinical_query(context.query)

    question_label = (
        "PATIENT QUESTION:" if context.audience == ContextAudience.PATIENT else "QUESTION:"
    )

    return f"EVIDENCE:\n\n{evidence_text}\n\n{question_label}\n{sanitized_query}"


def build_ollama_messages(context: AssembledContext) -> list[dict[str, str]]:
    """Build messages list with audience-specific system instructions and sanitized user context."""
    if context.audience == ContextAudience.PATIENT:
        system_content = format_ollama_patient_system_prompt()
    else:
        system_content = format_ollama_clinician_system_prompt()

    user_content = format_ollama_user_message(context)

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


class OllamaAnswerGenerator:
    """Ollama local AI provider adapter implementing AnswerGenerator."""

    def __init__(
        self,
        base_url: str = DEFAULT_OLLAMA_BASE_URL,
        model: str = DEFAULT_OLLAMA_MODEL,
        timeout_seconds: float = DEFAULT_OLLAMA_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client = client

    @property
    def base_url(self) -> str:
        """The base URL for Ollama HTTP API."""
        return self._base_url

    @property
    def model(self) -> str:
        """The configured Ollama model identifier."""
        return self._model

    @property
    def timeout_seconds(self) -> float:
        """The timeout in seconds for HTTP requests to Ollama."""
        return self._timeout_seconds

    async def generate_answer(
        self,
        context: AssembledContext,
    ) -> GeneratedAnswer:
        """Synthesize a clinical answer via Ollama structured output."""
        if not context.items:
            return GeneratedAnswer(
                answer=EMPTY_EVIDENCE_ANSWER,
                citations=(),
                provider="ollama",
                model=self._model,
                generated_at=datetime.now(UTC),
            )

        messages = build_ollama_messages(context)
        endpoint = f"{self._base_url}/api/chat"

        request_body = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": OLLAMA_ANSWER_SCHEMA,
            "options": {
                "temperature": 0.0,
            },
        }

        response = await self._send_request(endpoint, request_body)
        payload = self._parse_response(response)

        # Map valid 1-based cited indices back to CitationReference objects
        valid_cited = {idx for idx in payload.cited_indices if isinstance(idx, int) and idx > 0}
        citations: list[CitationReference] = []
        for item in context.items:
            if item.citation_index in valid_cited:
                citations.append(
                    CitationReference(
                        citation_index=item.citation_index,
                        record_id=item.record_id,
                        category_code=item.category_code,
                        chunk_index=item.chunk_index,
                    )
                )

        return GeneratedAnswer(
            answer=payload.answer,
            citations=tuple(citations),
            provider="ollama",
            model=self._model,
            generated_at=datetime.now(UTC),
        )

    async def _send_request(
        self,
        endpoint: str,
        body: dict[str, Any],
    ) -> httpx.Response:
        """Send POST request to Ollama with timeout and map connection/timeout errors."""
        try:
            if self._client is not None:
                return await self._client.post(
                    endpoint,
                    json=body,
                    timeout=self._timeout_seconds,
                )
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                return await client.post(endpoint, json=body)
        except (httpx.TimeoutException, TimeoutError):
            raise OllamaTimeoutError("Local AI answer generation timed out.") from None
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError):
            raise OllamaUnavailableError(
                "Local AI service (Ollama) is unavailable. Please ensure Ollama is running."
            ) from None
        except httpx.HTTPError as exc:
            raise OllamaProviderError(f"HTTP communication error with Ollama: {exc}") from None
        except Exception as exc:
            raise OllamaProviderError(
                f"Unexpected error communicating with Ollama: {exc}"
            ) from None

    def _parse_response(self, response: httpx.Response) -> OllamaAnswerPayload:
        """Validate and parse HTTP response into structured OllamaAnswerPayload."""
        if response.status_code == 503:
            raise OllamaUnavailableError(
                "Local AI service (Ollama) is unavailable. Please ensure Ollama is running."
            )
        if response.status_code in (408, 504):
            raise OllamaTimeoutError("Local AI answer generation timed out.")
        if response.status_code != 200:
            raise OllamaResponseError(
                f"Local AI service returned HTTP status {response.status_code}."
            )

        try:
            data = response.json()
        except Exception:
            raise OllamaResponseError(
                "Local AI service returned an invalid JSON response."
            ) from None

        if not isinstance(data, dict):
            raise OllamaResponseError("Local AI service returned a non-object JSON response.")

        message = data.get("message")
        if not isinstance(message, dict):
            raise OllamaResponseError("Local AI service response missing message object.")

        raw_content = message.get("content")
        if not raw_content or not isinstance(raw_content, str) or not raw_content.strip():
            raise OllamaResponseError("Local AI service returned an empty response.")

        content = raw_content.strip()
        # Strip potential markdown code fences if wrapped by the model
        if content.startswith("```"):
            lines = content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        try:
            parsed_content = json.loads(content)
        except Exception:
            raise OllamaResponseError(
                "Local AI service message content is not valid JSON."
            ) from None

        if not isinstance(parsed_content, dict):
            raise OllamaResponseError("Local AI service message content is not a JSON object.")

        try:
            payload = OllamaAnswerPayload.model_validate(parsed_content)
        except Exception:
            raise OllamaResponseError(
                "Local AI service response failed schema validation."
            ) from None

        if not payload.answer.strip():
            raise OllamaResponseError("Local AI service returned an empty answer.")

        return payload
