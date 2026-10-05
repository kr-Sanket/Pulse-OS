"""AI search API schemas — camelCase wire shapes (docs/API_GUIDELINES.md)."""

from uuid import UUID

from app.shared.schemas import ApiModel


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
