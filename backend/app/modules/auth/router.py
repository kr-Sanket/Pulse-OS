"""Auth endpoints. M0.3 Part 2 exposes only identity introspection — registration and
claim provisioning arrive with the patients module (Part 3).
"""

from fastapi import APIRouter

from app.modules.auth.dependencies import CurrentUser
from app.modules.auth.schemas import AuthenticatedUserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=AuthenticatedUserResponse)
async def read_current_user(user: CurrentUser) -> AuthenticatedUserResponse:
    """Return the caller's authenticated identity.

    Roles: any authenticated, provisioned user. Failure modes: 401 (missing/malformed/
    invalid/expired token), 403 (unprovisioned account), 503 (provider unavailable).
    """
    return AuthenticatedUserResponse(
        user_id=user.user_id, firebase_uid=user.firebase_uid, role=user.role
    )
