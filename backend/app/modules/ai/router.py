"""AI retrieval endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.ai.dependencies import AIQueryServiceDep
from app.modules.ai.schemas import AIChunkSearchListResponse, AIChunkSearchResponse
from app.modules.auth.dependencies import RequireDoctor
from app.modules.auth.domain import AuthenticatedUser
from app.modules.consent.dependencies import CategoryVocabularyDep

DoctorUser = Annotated[AuthenticatedUser, Depends(RequireDoctor)]

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

