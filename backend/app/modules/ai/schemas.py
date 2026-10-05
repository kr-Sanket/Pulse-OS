"""AI search API schemas — camelCase wire shapes (docs/API_GUIDELINES.md)."""

from uuid import UUID

from pydantic import Field

from app.shared.schemas import ApiModel, RequestModel


class AIChunkSearchResponse(ApiModel):
    """One retrieved AI chunk in search results."""

    chunk_id: UUID
    record_id: UUID
    category_code: str
    chunk_index: int
    content: str
    token_count: int


class AIChunkSearchListResponse(ApiModel):
    """Enveloped list of AI chunk search results."""

    items: list[AIChunkSearchResponse]


AISearchResponse = AIChunkSearchListResponse


class AIAnswerRequest(RequestModel):
    """Request payload for synthesizing a clinical answer."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Clinical query or question to be answered from patient records.",
    )
    max_tokens: int = Field(
        default=1000,
        gt=0,
        le=4000,
        description="Maximum token budget for assembled clinical context.",
    )


class AICitationResponse(ApiModel):
    """Citation provenance linking synthesized text to an underlying medical record."""

    citation_index: int
    record_id: UUID
    category_code: str
    chunk_index: int


class AIAnswerResponse(ApiModel):
    """Synthesized clinical answer and verifiable provenance."""

    answer: str
    citations: list[AICitationResponse]
    provider: str
    model: str
    disclaimer: str
