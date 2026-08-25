"""Infrastructure probes: /health (liveness) and /ready (DB + Redis connectivity).

The readiness checks are FastAPI dependencies so tests can override them without
touching real services (docs/DEVELOPMENT_GUIDE.md: external services are faked in tests).
"""

import logging
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings, get_settings

logger = logging.getLogger("pulseos.health")

router = APIRouter(tags=["infra"])

_CHECK_TIMEOUT_SECONDS = 2.0


async def database_ready(request: Request) -> bool:
    """True when a `SELECT 1` succeeds on the application engine."""
    engine: AsyncEngine = request.app.state.db_engine
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        logger.warning("database readiness check failed", exc_info=True)
        return False
    return True


async def redis_ready(settings: Annotated[Settings, Depends(get_settings)]) -> bool:
    """True when Redis answers a PING."""
    client = aioredis.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=_CHECK_TIMEOUT_SECONDS,
        socket_timeout=_CHECK_TIMEOUT_SECONDS,
    )
    try:
        await client.ping()
    except Exception:
        logger.warning("redis readiness check failed", exc_info=True)
        return False
    finally:
        await client.aclose()
    return True


@router.get("/health")
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
    """Liveness probe: the process is up. No dependency checks (that is /ready)."""
    return {"status": "ok", "environment": settings.environment}


@router.get("/ready")
async def ready(
    database_ok: Annotated[bool, Depends(database_ready)],
    redis_ok: Annotated[bool, Depends(redis_ready)],
) -> JSONResponse:
    """Readiness probe: 200 when every dependency answers, 503 otherwise."""
    checks = {
        "database": "ok" if database_ok else "failed",
        "redis": "ok" if redis_ok else "failed",
    }
    if database_ok and redis_ok:
        return JSONResponse({"status": "ready", "checks": checks})
    return JSONResponse({"status": "unready", "checks": checks}, status_code=503)
