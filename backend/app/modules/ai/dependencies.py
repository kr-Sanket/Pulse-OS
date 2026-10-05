from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.modules.ai.query import AIQueryService
from app.modules.ai.repository import AIRepository
from app.modules.ai.service import AIRetrievalService
from app.modules.consent.dependencies import get_consent_service
from app.modules.consent.service import ConsentService


def get_ai_query_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    consent: Annotated[ConsentService, Depends(get_consent_service)],
) -> AIQueryService:
    repository = AIRepository(session)
    retrieval = AIRetrievalService(repository)

    return AIQueryService(
        retrieval=retrieval,
        consent=consent,
    )


AIQueryServiceDep = Annotated[
    AIQueryService,
    Depends(get_ai_query_service),
]