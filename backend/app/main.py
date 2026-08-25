"""Application entry point.

M0.1 scaffold: app factory + liveness endpoint only. Module routers are mounted here
as milestones land (see .claude/ROADMAP.md). Run locally with:

    uvicorn app.main:app --reload
"""

from fastapi import FastAPI

from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
    )

    @application.get("/health", tags=["infra"])
    async def health() -> dict[str, str]:
        """Liveness probe. Readiness (/ready, with DB/Redis checks) arrives with M0.3."""
        return {"status": "ok", "environment": settings.environment}

    return application


app = create_app()
