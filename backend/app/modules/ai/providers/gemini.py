"""Gemini answer generation provider adapter."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Final
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.ai.context import AssembledContext
from app.modules.ai.generation import (
    AnswerGenerator,
    CitationReference,
    GeneratedAnswer,
)
from app.modules.ai.text import sanitize_clinical_query

DEFAULT_GEMINI_TIMEOUT_SECONDS: Final[float] = 15.0

EMPTY_EVIDENCE_ANSWER: Final[str] = (
    "The available medical records do not contain information regarding the requested topic."
)


class GeminiProviderError(Exception):
    """Base exception for Gemini provider errors."""


class GeminiRateLimitError(GeminiProviderError):
    """Gemini API rate limit exceeded (HTTP 429)."""


class GeminiTimeoutError(GeminiProviderError):
    """Gemini API request timed out."""


class GeminiUnavailableError(GeminiProviderError):
    """Gemini API service unavailable or 5xx."""


class GeminiResponseError(GeminiProviderError):
    """Gemini API returned malformed or unparseable response."""


class GeminiSafetyError(GeminiProviderError):
    """Gemini response blocked by content safety filters."""


class GeminiAnswerPayload(BaseModel):
    """Provider-local structured response payload from Gemini."""

    answer: str = Field(
        description="The synthesized clinical answer citing sources using bracketed notation."
    )
    cited_indices: list[int] = Field(
        default_factory=list,
        description="List of 1-based citation indices cited in the answer.",
    )


def format_gemini_prompt(context: AssembledContext) -> str:
    """Format safe model-facing prompt strictly from allowed evidence fields."""
    evidence_blocks: list[str] = []
    for item in context.items:
        evidence_blocks.append(
            f"[{item.citation_index}] Category: {item.category_code} (Chunk: {item.chunk_index})\n"
            f"Content: {item.content}"
        )

    evidence_text = "\n\n".join(evidence_blocks)
    sanitized_query = sanitize_clinical_query(context.query)

    return (
        "SYSTEM:\n"
        "You are a clinical information retrieval and synthesis assistant.\n\n"
        "Rules:\n"
        "- Use only the provided evidence.\n"
        "- Do not invent or infer unsupported clinical facts.\n"
        "- Every clinical factual statement must cite evidence using [n].\n"
        "- If the evidence does not answer the question, say:\n"
        '  "The available medical records do not contain information regarding the requested topic."\n'
        "- Do not provide an autonomous diagnosis or medical advice.\n\n"
        f"EVIDENCE:\n\n{evidence_text}\n\n"
        f"QUESTION:\n{sanitized_query}"
    )


class GeminiAnswerGenerator:
    """Gemini provider adapter implementing AnswerGenerator."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-3.8-flash",
        client: Any | None = None,
        timeout_seconds: float = DEFAULT_GEMINI_TIMEOUT_SECONDS,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

        if client is not None:
            self._client = client
        elif api_key:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(
                    retry_options=types.HttpRetryOptions(attempts=3)
                ),
            )
        else:
            raise ValueError(
                "Either client or api_key must be provided for GeminiAnswerGenerator"
            )

    @property
    def model(self) -> str:
        """The configured Gemini model identifier."""
        return self._model

    async def generate_answer(
        self,
        context: AssembledContext,
    ) -> GeneratedAnswer:
        """Synthesize a clinical answer via Gemini structured output."""
        if not context.items:
            return GeneratedAnswer(
                answer=EMPTY_EVIDENCE_ANSWER,
                citations=(),
                provider="gemini",
                model=self._model,
                generated_at=datetime.now(timezone.utc),
            )

        prompt = format_gemini_prompt(context)

        from google.genai import types

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=GeminiAnswerPayload,
        )

        try:
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=config,
                ),
                timeout=self._timeout_seconds,
            )
        except (TimeoutError, asyncio.TimeoutError):
            raise GeminiTimeoutError("Gemini API request timed out.") from None
        except GeminiProviderError:
            raise
        except Exception as exc:
            self._normalize_exception(exc)

        self._check_safety_block(response)
        payload = self._parse_payload(response)

        # Validate citation indices against context items, preserving context order
        cited_set = set(payload.cited_indices)
        citations: list[CitationReference] = []
        for item in context.items:
            if item.citation_index in cited_set:
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
            provider="gemini",
            model=self._model,
            generated_at=datetime.now(timezone.utc),
        )

    def _check_safety_block(self, response: Any) -> None:
        """Verify the response was not blocked by safety filters."""
        candidates = getattr(response, "candidates", None)
        if candidates:
            for cand in candidates:
                finish_reason = getattr(cand, "finish_reason", None)
                if finish_reason is not None:
                    reason_str = str(finish_reason).upper()
                    if any(
                        term in reason_str
                        for term in ("SAFETY", "BLOCKLIST", "PROHIBITED")
                    ):
                        raise GeminiSafetyError(
                            "Gemini generation was blocked by safety filters."
                        )

    def _parse_payload(self, response: Any) -> GeminiAnswerPayload:
        """Parse structured payload from parsed attribute or JSON text."""
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, GeminiAnswerPayload):
            return parsed

        raw_text = getattr(response, "text", None)
        if raw_text:
            try:
                data = json.loads(raw_text)
                return GeminiAnswerPayload.model_validate(data)
            except Exception:
                raise GeminiResponseError(
                    "Gemini API returned an invalid response structure."
                ) from None

        raise GeminiResponseError("Gemini API returned an empty response.")

    def _normalize_exception(self, exc: Exception) -> None:
        """Translate raw provider SDK exceptions into domain exceptions without leaking PHI."""
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        exc_str = str(exc).upper()

        if code == 429 or "RESOURCE_EXHAUSTED" in exc_str or "RATE" in exc_str:
            raise GeminiRateLimitError("Gemini API rate limit exceeded.") from None

        if (
            code in (500, 502, 503, 504)
            or "UNAVAILABLE" in exc_str
            or "SERVER_ERROR" in exc_str
        ):
            raise GeminiUnavailableError("Gemini API service is unavailable.") from None

        if code == 408 or "DEADLINE" in exc_str or "TIMEOUT" in exc_str:
            raise GeminiTimeoutError("Gemini API request timed out.") from None

        raise GeminiProviderError("Gemini API request failed.") from None
