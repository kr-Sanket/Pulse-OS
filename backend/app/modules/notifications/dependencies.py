"""FastAPI dependencies and domain-error mapping for notifications module (ADR-031)."""

from typing import Annotated, Any

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.modules.auth.dependencies import require_role
from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.notifications.errors import (
    NotificationError,
    NotificationNotFoundError,
)
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.service import NotificationService
from app.shared.pagination import CursorKey, InvalidCursorError, decode_cursor

# Content type spec for OpenAPI error responses
PROBLEM: dict[str, dict[str, Any]] = {"application/problem+json": {}}

# Composite role gate: only PATIENT and DOCTOR may access notification endpoints
RequireNotificationUser = require_role(Role.PATIENT, Role.DOCTOR)


def to_http_error(exc: NotificationError) -> HTTPException:
    """Domain -> RFC 7807 translation for notifications.

    404 Not Found is returned when a notification does not exist OR belongs to another
    user, preventing cross-user presence enumeration.
    """
    if isinstance(exc, NotificationNotFoundError):
        return HTTPException(status_code=404, detail="Notification not found.")
    return HTTPException(status_code=500, detail="The operation failed unexpectedly.")


def parse_cursor(cursor: str | None) -> CursorKey | None:
    """Decode an opaque pagination cursor; forged/corrupted cursor is HTTP 422."""
    if cursor is None:
        return None
    try:
        return decode_cursor(cursor)
    except InvalidCursorError:
        raise HTTPException(status_code=422, detail="Invalid pagination cursor.") from None


def get_notification_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> NotificationRepository:
    return NotificationRepository(session)


def get_notification_service(
    repository: Annotated[NotificationRepository, Depends(get_notification_repository)],
) -> NotificationService:
    return NotificationService(repository)


NotificationServiceDep = Annotated[NotificationService, Depends(get_notification_service)]
NotificationUserDep = Annotated[AuthenticatedUser, Depends(RequireNotificationUser)]
