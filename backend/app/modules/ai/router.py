"""AI retrieval and answer generation endpoints."""

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.modules.ai.dependencies import (
    AIQueryServiceDep,
    AnswerGeneratorDep,
    RequestContextDep,
    to_http_error,
)
from app.modules.ai.schemas import (
    AIAnswerRequest,
    AIAnswerResponse,
    AIChunkSearchListResponse,
    AIChunkSearchResponse,
    AICitationResponse,
)
from app.modules.auth.dependencies import RequireDoctor, RequirePatient, rate_limited
from app.modules.auth.domain import AuthenticatedUser
from app.modules.consent.dependencies import CategoryVocabularyDep
from app.modules.patients.dependencies import PatientServiceDep

DoctorUser = Annotated[AuthenticatedUser, Depends(RequireDoctor)]
PatientUser = Annotated[AuthenticatedUser, Depends(RequirePatient)]

DEFAULT_CLINICAL_DISCLAIMER: Final[str] = (
    "This clinical summary is an AI-assisted synthesis of available records and "
    "does not constitute medical advice or a definitive diagnosis. "
    "Review primary records before clinical decisions."
)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get(
    "/patients/{patient_id}/search",
    response_model=AIChunkSearchListResponse,
    responses={429: {"description": "Rate limit exceeded"}},
)
async def search_patient_records(
    patient_id: UUID,
    user: DoctorUser,
    _limit: Annotated[AuthenticatedUser, Depends(rate_limited("ai_search"))],
    service: AIQueryServiceDep,
    vocabulary: CategoryVocabularyDep,
    request_context: RequestContextDep,
    query: Annotated[str, Query(min_length=1, max_length=500)],
) -> AIChunkSearchListResponse:
    """Ranked chunk text from this patient's records within the clinician's granted scope.

    Roles: DOCTOR. Consent requirement: only categories the clinician holds an active
    grant for are searched, and patient-hidden records are excluded. Rate limited
    (``ai_search``). Audited: exactly one event per request — ``RECORDS_SEARCHED`` when a
    scope was searched, ``ACCESS_DENIED`` when there was none. The query text is never
    stored or logged by the application; note that it travels in the URL.
    Failure modes: 401, 403 (wrong role), 422 (query missing or over 500 characters), 429.
    """
    chunks = await service.search_records(
        user,
        patient_id=patient_id,
        query=query,
        request_context=request_context,
    )
    return AIChunkSearchListResponse(
        items=[
            AIChunkSearchResponse(
                chunk_id=chunk.chunk_id,
                record_id=chunk.record_id,
                category_code=vocabulary.by_id[chunk.category_id],
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                token_count=chunk.token_count,
            )
            for chunk in chunks
        ]
    )


@router.post("/patients/{patient_id}/answer", response_model=AIAnswerResponse)
async def generate_patient_answer(
    patient_id: UUID,
    user: DoctorUser,
    _limit: Annotated[AuthenticatedUser, Depends(rate_limited("ai_generate"))],
    body: AIAnswerRequest,
    service: AIQueryServiceDep,
    generator: AnswerGeneratorDep,
    vocabulary: CategoryVocabularyDep,
    request_context: RequestContextDep,
) -> AIAnswerResponse:
    try:
        result = await service.generate_answer(
            user,
            patient_id=patient_id,
            query=body.query,
            category_codes=vocabulary.by_id,
            generator=generator,
            max_tokens=body.max_tokens,
            request_context=request_context,
        )
    except Exception as exc:
        raise to_http_error(exc) from exc

    return AIAnswerResponse(
        answer=result.answer,
        citations=[
            AICitationResponse(
                citation_index=cit.citation_index,
                record_id=cit.record_id,
                category_code=cit.category_code,
                chunk_index=cit.chunk_index,
            )
            for cit in result.citations
        ],
        provider=result.provider,
        model=result.model,
        disclaimer=DEFAULT_CLINICAL_DISCLAIMER,
    )


@router.post("/me/answer", response_model=AIAnswerResponse)
async def generate_patient_self_answer(
    user: PatientUser,
    _limit: Annotated[AuthenticatedUser, Depends(rate_limited("ai_generate"))],
    body: AIAnswerRequest,
    service: AIQueryServiceDep,
    patient_service: PatientServiceDep,
    generator: AnswerGeneratorDep,
    vocabulary: CategoryVocabularyDep,
    request_context: RequestContextDep,
) -> AIAnswerResponse:
    patient = await patient_service.get_profile(user.user_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient profile not found.")

    try:
        result = await service.generate_self_answer(
            user,
            patient_id=patient.id,
            query=body.query,
            category_codes=vocabulary.by_id,
            generator=generator,
            max_tokens=body.max_tokens,
            request_context=request_context,
        )
    except Exception as exc:
        raise to_http_error(exc) from exc

    return AIAnswerResponse(
        answer=result.answer,
        citations=[
            AICitationResponse(
                citation_index=cit.citation_index,
                record_id=cit.record_id,
                category_code=cit.category_code,
                chunk_index=cit.chunk_index,
            )
            for cit in result.citations
        ],
        provider=result.provider,
        model=result.model,
        disclaimer=DEFAULT_CLINICAL_DISCLAIMER,
    )
