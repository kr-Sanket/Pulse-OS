"""Auth API schemas (wire shapes only — internal types live in domain.py)."""

from uuid import UUID

from app.modules.auth.domain import Role
from app.shared.schemas import ApiModel


class AuthenticatedUserResponse(ApiModel):
    user_id: UUID
    firebase_uid: str
    role: Role
