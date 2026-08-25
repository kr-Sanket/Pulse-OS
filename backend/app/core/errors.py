"""Centralized exception handling — RFC 7807 Problem Details (docs/API_GUIDELINES.md §Errors).

All error responses are ``application/problem+json`` with ``type``, ``title``, ``status``,
``instance`` (the request path), optional ``detail``, and ``errors[]`` for field-level
validation failures. Modules raise domain exceptions or ``HTTPException``; services never
construct HTTP responses themselves.
"""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.middleware import REQUEST_ID_HEADER

logger = logging.getLogger("pulseos.errors")

PROBLEM_CONTENT_TYPE = "application/problem+json"


def problem_response(
    request: Request,
    *,
    status_code: int,
    title: str,
    detail: str | None = None,
    errors: list[dict[str, str]] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status_code,
        "instance": request.url.path,
    }
    if detail is not None:
        body["detail"] = detail
    if errors is not None:
        body["errors"] = errors

    headers: dict[str, str] = {}
    request_id: str | None = getattr(request.state, "request_id", None)
    if request_id is not None:
        headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(
        body, status_code=status_code, media_type=PROBLEM_CONTENT_TYPE, headers=headers
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        title = HTTPStatus(exc.status_code).phrase
        detail = exc.detail if isinstance(exc.detail, str) and exc.detail != title else None
        return problem_response(request, status_code=exc.status_code, title=title, detail=detail)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "message": str(error["msg"]),
            }
            for error in exc.errors()
        ]
        return problem_response(
            request,
            status_code=422,
            title="Validation Error",
            detail="Request validation failed.",
            errors=errors,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Full traceback goes to the log; the client never sees internals. This handler
        # runs outside RequestContextMiddleware, so the request id comes from request.state.
        logger.exception(
            "unhandled exception",
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        return problem_response(
            request,
            status_code=500,
            title="Internal Server Error",
            detail="An unexpected error occurred.",
        )
