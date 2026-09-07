"""Application entry point.

App factory, lifespan-managed infrastructure (database engine/session factory, object
storage, job queue, auth provider), structured JSON logging with request-id propagation,
RFC 7807 exception handlers, and the /health + /ready probes. Module routers are mounted
here as milestones land (see .claude/ROADMAP.md). Run locally with:

    uvicorn app.main:app --reload
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.db import create_db_engine, create_session_factory
from app.core.errors import register_exception_handlers
from app.core.health import router as health_router
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.queue import ArqJobQueue
from app.core.ratelimit import build_rate_limiter
from app.modules.auth.firebase import FirebaseAuthProvider
from app.modules.auth.router import router as auth_router
from app.modules.consent.router import (
    access_requests_router,
    audit_logs_router,
    consent_grants_router,
    hospital_audit_logs_router,
)
from app.modules.patients.router import router as patients_router
from app.modules.records.organizations_router import doctors_router, hospitals_router
from app.modules.records.router import (
    categories_router,
    granted_records_router,
    records_router,
)
from app.modules.records.storage import S3ObjectStorage

API_V1_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_db_engine(settings)
    app.state.db_engine = engine
    app.state.db_sessionmaker = create_session_factory(engine)
    # Lazy-initializing providers (ADR-011/005/014): the app boots without Firebase,
    # MinIO, or Redis; tests override the corresponding get_* dependencies with fakes.
    app.state.auth_provider = FirebaseAuthProvider(settings)
    app.state.object_storage = S3ObjectStorage(settings)
    job_queue = ArqJobQueue(settings.redis_url)
    app.state.job_queue = job_queue
    # Shares Redis with arq but not its connection: arq owns a pool shaped for job
    # dispatch, and one INCR per request has different lifetime needs (ADR-024).
    rate_limiter = build_rate_limiter(settings)
    app.state.rate_limiter = rate_limiter
    yield
    await rate_limiter.aclose()
    await job_queue.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.add_middleware(RequestContextMiddleware)
    # Browser portals call the API cross-origin in dev; auth is bearer-token based,
    # so no cookies/credentials are ever shared (docs/SECURITY.md).
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
        expose_headers=["X-Request-Id"],
    )
    register_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(auth_router, prefix=API_V1_PREFIX)
    application.include_router(patients_router, prefix=API_V1_PREFIX)
    application.include_router(hospitals_router, prefix=API_V1_PREFIX)
    application.include_router(doctors_router, prefix=API_V1_PREFIX)
    application.include_router(records_router, prefix=API_V1_PREFIX)
    application.include_router(categories_router, prefix=API_V1_PREFIX)
    application.include_router(granted_records_router, prefix=API_V1_PREFIX)
    application.include_router(access_requests_router, prefix=API_V1_PREFIX)
    application.include_router(consent_grants_router, prefix=API_V1_PREFIX)
    application.include_router(audit_logs_router, prefix=API_V1_PREFIX)
    # /hospitals/me/audit-logs is consent-owned data on a records-owned URL prefix (ADR-023).
    application.include_router(hospital_audit_logs_router, prefix=API_V1_PREFIX)
    return application


app = create_app()
