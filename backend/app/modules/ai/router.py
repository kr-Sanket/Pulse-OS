"""AI retrieval and answer generation endpoints."""

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.ai.dependencies import (
    AIQueryServiceDep,
    AnswerGeneratorDep,
    RequestContextDep,
    to_http_error,
)
from app.modules.ai.schemas import (
    AIAnswerRequest,
    AIAnswerResponse,
    AICitationResponse,
    AIChunkSearchListResponse,
    AIChunkSearchResponse,
)
from app.modules.auth.dependencies import RequireDoctor
from app.modules.auth.domain import AuthenticatedUser
from app.modules.consent.dependencies import CategoryVocabularyDep

DoctorUser = Annotated[AuthenticatedUser, Depends(RequireDoctor)]

DEFAULT_CLINICAL_DISCLAIMER: Final[str] = (
    "This clinical summary is an AI-assisted synthesis of available records and "
    "does not constitute medical advice or a definitive diagnosis. "
    "Review primary records before clinical decisions."
)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/patients/{patient_id}/search", response_model=AIChunkSearchListResponse)
async def search_patient_records(
    patient_id: UUID,
    user: DoctorUser,
    service: AIQueryServiceDep,
    vocabulary: CategoryVocabularyDep,
    query: Annotated[str, Query(min_length=1, max_length=500)],
) -> AIChunkSearchListResponse:
    chunks = await service.search(
        user,
        patient_id=patient_id,
        query=query,
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

