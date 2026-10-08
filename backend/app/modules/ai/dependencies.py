from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_db_session
from app.modules.ai.generation import AnswerGenerator, FakeAnswerGenerator
from app.modules.ai.providers.gemini import (
    GeminiProviderError,
    GeminiRateLimitError,
    GeminiResponseError,
    GeminiSafetyError,
    GeminiTimeoutError,
    GeminiUnavailableError,
)
from app.modules.ai.query import AIQueryService
from app.modules.ai.repository import AIRepository
from app.modules.ai.service import AIRetrievalService
from app.modules.consent.dependencies import get_consent_service
from app.modules.consent.service import ConsentService


def get_request_context(request: Request) -> str | None:
    """The X-Request-Id correlation key carried by audit events."""
    context: str | None = getattr(request.state, "request_id", None)
    return context


RequestContextDep = Annotated[str | None, Depends(get_request_context)]


def get_ai_query_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    consent: Annotated[ConsentService, Depends(get_consent_service)],
) -> AIQueryService:
    repository = AIRepository(session)
    retrieval = AIRetrievalService(repository)

    return AIQueryService(
        retrieval=retrieval,
        consent=consent,
        auditor=consent,
    )


AIQueryServiceDep = Annotated[
    AIQueryService,
    Depends(get_ai_query_service),
]


class AIConfigurationError(HTTPException, RuntimeError):
    """Raised when the configured AI provider is missing required configuration."""

    def __init__(
        self,
        msg: str = "PULSEOS_GEMINI_API_KEY must be set when PULSEOS_AI_PROVIDER is 'gemini'",
    ) -> None:
        self.msg = msg
        HTTPException.__init__(
            self,
            status_code=503,
            detail="AI answer generation service is unconfigured.",
        )
        RuntimeError.__init__(self, msg)

    def __str__(self) -> str:
        return self.msg


def get_answer_generator(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnswerGenerator:
    """Dependency provider for AnswerGenerator based on configuration."""
    if settings.ai_provider == "gemini":
        if not settings.gemini_api_key:
            raise AIConfigurationError(
                "PULSEOS_GEMINI_API_KEY must be set when PULSEOS_AI_PROVIDER is 'gemini'"
            )
        from app.modules.ai.providers.gemini import GeminiAnswerGenerator

        return GeminiAnswerGenerator(
            api_key=settings.gemini_api_key,
            model=settings.ai_model,
            timeout_seconds=settings.gemini_timeout_seconds,
        )

    return FakeAnswerGenerator()


AnswerGeneratorDep = Annotated[
    AnswerGenerator,
    Depends(get_answer_generator),
]


def to_http_error(exc: Exception) -> HTTPException:
    """Map provider and generation exceptions to RFC 7807 problem HTTPExceptions."""
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, GeminiRateLimitError):
        return HTTPException(
            status_code=429,
            detail="AI service rate limit exceeded. Please retry later.",
        )
    if isinstance(exc, GeminiTimeoutError):
        return HTTPException(
            status_code=504,
            detail="AI answer generation timed out.",
        )
    if isinstance(exc, GeminiUnavailableError):
        return HTTPException(
            status_code=503,
            detail="AI service is temporarily unavailable. Please retry later.",
        )
    if isinstance(exc, GeminiSafetyError):
        return HTTPException(
            status_code=422,
            detail="AI answer generation was blocked by safety filters.",
        )
    if isinstance(exc, GeminiResponseError):
        return HTTPException(
            status_code=502,
            detail="AI service returned an invalid response.",
        )
    if isinstance(exc, RuntimeError) and "PULSEOS_GEMINI_API_KEY" in str(exc):
        return HTTPException(
            status_code=503,
            detail="AI answer generation service is unconfigured.",
        )
    if isinstance(exc, GeminiProviderError):
        return HTTPException(
            status_code=502,
            detail="AI answer generation failed.",
        )
    return HTTPException(
        status_code=500,
        detail="The AI operation failed unexpectedly.",
    )