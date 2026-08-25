"""Request-context middleware: request-id propagation + structured access log.

Access log fields: method, path (query string deliberately excluded — it may carry
identifiers), status code, duration in ms, and the request id via the logging contextvar.
"""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import request_id_var

logger = logging.getLogger("pulseos.access")

REQUEST_ID_HEADER = "X-Request-Id"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns/propagates X-Request-Id and emits one access-log line per request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        # Also on request.state: the global exception handler runs outside this
        # middleware's scope, after the contextvar has been reset.
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            self._log(request, status_code=500, started=started)
            raise
        else:
            response.headers[REQUEST_ID_HEADER] = request_id
            self._log(request, status_code=response.status_code, started=started)
            return response
        finally:
            request_id_var.reset(token)

    @staticmethod
    def _log(request: Request, *, status_code: int, started: float) -> None:
        logger.info(
            "request completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
