from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_db_session
from app.modules.ai.generation import AnswerGenerator, FakeAnswerGenerator
from app.modules.ai.providers.ollama import (
    OllamaProviderError,
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
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
        msg: str = "AI answer generation service is unconfigured.",
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
    if settings.ai_provider == "fake":
        return FakeAnswerGenerator()

    from app.modules.ai.providers.ollama import OllamaAnswerGenerator

    return OllamaAnswerGenerator(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )


AnswerGeneratorDep = Annotated[
    AnswerGenerator,
    Depends(get_answer_generator),
]


def to_http_error(exc: Exception) -> HTTPException:
    """Map provider and generation exceptions to RFC 7807 problem HTTPExceptions."""
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, OllamaTimeoutError):
        return HTTPException(
            status_code=504,
            detail="Local AI answer generation timed out.",
        )
    if isinstance(exc, OllamaUnavailableError):
        return HTTPException(
            status_code=503,
            detail="Local AI service (Ollama) is unavailable. Please ensure Ollama is running.",
        )
    if isinstance(exc, OllamaResponseError):
        return HTTPException(
            status_code=502,
            detail="Local AI service returned an invalid response.",
        )
    if isinstance(exc, OllamaProviderError):
        return HTTPException(
            status_code=502,
            detail="Local AI operation failed.",
        )
    return HTTPException(
        status_code=500,
        detail="The AI operation failed unexpectedly.",
    )
