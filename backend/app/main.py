"""Application entry point.

M0.3 plumbing: app factory, lifespan-managed database engine/session factory, structured
JSON logging with request-id propagation, RFC 7807 exception handlers, and the /health +
/ready infrastructure probes. Module routers are mounted here as milestones land
(see .claude/ROADMAP.md). Run locally with:

    uvicorn app.main:app --reload
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.db import create_db_engine, create_session_factory
from app.core.errors import register_exception_handlers
from app.core.health import router as health_router
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.modules.auth.firebase import FirebaseAuthProvider
from app.modules.auth.router import router as auth_router

API_V1_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_db_engine(settings)
    app.state.db_engine = engine
    app.state.db_sessionmaker = create_session_factory(engine)
    # Lazy-initializing provider (ADR-011): the app boots without Firebase credentials;
    # tests override the get_auth_provider dependency with FakeAuthProvider.
    app.state.auth_provider = FirebaseAuthProvider(settings)
    yield
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
    register_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(auth_router, prefix=API_V1_PREFIX)
    return application


app = create_app()
