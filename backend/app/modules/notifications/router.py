"""API router for notifications module (ADR-031)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.modules.notifications.dependencies import (
    PROBLEM,
    NotificationServiceDep,
    NotificationUserDep,
    parse_cursor,
    to_http_error,
)
from app.modules.notifications.errors import NotificationError
from app.modules.notifications.schemas import (
    MarkAllReadResponse,
    NotificationListResponse,
    NotificationResponse,
    UnreadCountResponse,
)
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get(
    "",
    response_model=NotificationListResponse,
    responses={
        401: {"content": PROBLEM, "description": "Unauthenticated."},
        403: {"content": PROBLEM, "description": "Insufficient role for this operation."},
        422: {"content": PROBLEM, "description": "Invalid pagination cursor or limit."},
    },
)
async def list_notifications(
    user: NotificationUserDep,
    service: NotificationServiceDep,
    cursor: Annotated[str | None, Query(description="Opaque keyset pagination cursor.")] = None,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_PAGE_SIZE,
            description="Page size (1-100).",
        ),
    ] = DEFAULT_PAGE_SIZE,
    unread_only: Annotated[
        bool,
        Query(
            alias="unreadOnly",
            description="Filter strictly for unread notifications.",
        ),
    ] = False,
) -> NotificationListResponse:
    """List notifications for the calling user with keyset cursor pagination."""
    cursor_key = parse_cursor(cursor)
    items, next_cursor = await service.list_notifications(
        user.user_id,
        cursor=cursor_key,
        limit=limit,
        unread_only=unread_only,
    )
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(item) for item in items],
        next_cursor=next_cursor,
    )


@router.get(
    "/unread-count",
    response_model=UnreadCountResponse,
    responses={
        401: {"content": PROBLEM, "description": "Unauthenticated."},
        403: {"content": PROBLEM, "description": "Insufficient role for this operation."},
    },
)
async def get_unread_count(
    user: NotificationUserDep,
    service: NotificationServiceDep,
) -> UnreadCountResponse:
    """Return the total number of unread notifications for the calling user."""
    count = await service.get_unread_count(user.user_id)
    return UnreadCountResponse(count=count)


@router.post(
    "/{id}/read",
    response_model=NotificationResponse,
    responses={
        401: {"content": PROBLEM, "description": "Unauthenticated."},
        403: {"content": PROBLEM, "description": "Insufficient role for this operation."},
        404: {"content": PROBLEM, "description": "Notification not found."},
    },
)
async def mark_notification_read(
    id: UUID,
    user: NotificationUserDep,
    service: NotificationServiceDep,
) -> NotificationResponse:
    """Mark a notification as read (idempotent)."""
    try:
        updated = await service.mark_read(id, user.user_id)
        return NotificationResponse.model_validate(updated)
    except NotificationError as exc:
        raise to_http_error(exc) from exc


@router.post(
    "/mark-all-read",
    response_model=MarkAllReadResponse,
    responses={
        401: {"content": PROBLEM, "description": "Unauthenticated."},
        403: {"content": PROBLEM, "description": "Insufficient role for this operation."},
    },
)
async def mark_all_notifications_read(
    user: NotificationUserDep,
    service: NotificationServiceDep,
) -> MarkAllReadResponse:
    """Bulk-mark all unread notifications for the calling user as read."""
    count = await service.mark_all_read(user.user_id)
    return MarkAllReadResponse(count=count)
