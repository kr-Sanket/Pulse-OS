"""consent dependency wiring + domain-error → RFC 7807 translation.

Composition only, no business logic — the same shape as
app/modules/records/dependencies.py: ``get_*`` factories assemble the service from
repositories that share the request's single session, and one ``to_http_error`` keeps
status-code mapping in a single place so routers stay thin and services never see HTTP.

Two collaborators come from ``records``, which owns the clinician and category tables this
module may not query (docs/SYSTEM_ARCHITECTURE.md rule 1). Both arrive through
``records.directory`` — that module's published seam — and the thin adapters below translate
its projections into the shapes consent declares:

- ``ClinicianDirectory`` — resolves a caller to a practitioner (declared in ``service``).
- ``CategoryVocabularySource`` — the record-category vocabulary in both directions, because
  the API speaks codes and the domain speaks UUIDs.

Importing ``records.directory`` and nothing deeper is deliberate: it imports nothing outside
``records``, so the edge that runs the other way — ``records.service`` asking
``consent.enforce`` for permission — cannot close into a cycle. Both dependencies are
ordinary overridable providers, so tests substitute fakes without touching app state.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Protocol
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.modules.consent.errors import (
    AccessDeniedError,
    ClinicianNotActiveError,
    ClinicianProfileNotFoundError,
    ConsentError,
    DuplicateDecisionError,
    DuplicateGrantError,
    DuplicateRequestCategoryError,
    EmptyCategorySelectionError,
    GrantNotFoundError,
    PatientProfileNotFoundError,
    RequestNotDecidableError,
    RequestNotFoundError,
    UnknownPatientError,
    UnrequestedCategoryError,
)
from app.modules.consent.repository import (
    AuditLogRepository,
    ConsentDecisionRepository,
    ConsentGrantRepository,
    ConsentRequestCategoryRepository,
    ConsentRequestRepository,
)
from app.modules.consent.service import Clinician, ClinicianDirectory, ConsentService
from app.modules.patients.directory import PatientDirectoryService
from app.modules.patients.repository import PatientRepository
from app.modules.records import directory as records_directory
from app.shared.pagination import CursorKey, InvalidCursorError, decode_cursor

logger = logging.getLogger(__name__)

#: Declared on every consent endpoint so the generated contract lists the failures the
#: docstrings describe, not just the success case. The problem+json body shape itself is a
#: cross-cutting model that belongs in app/shared — see the router's deferred notes.
PROBLEM: dict[str, dict[str, Any]] = {"application/problem+json": {}}

#: Shape of a FastAPI ``responses=`` block, so the per-endpoint failure lists type-check.
type ResponseSpec = dict[int | str, dict[str, Any]]


def to_http_error(exc: ConsentError) -> HTTPException:
    """Domain → RFC 7807 translation shared by the consent routers.

    The 403-vs-404 rule (docs/API_GUIDELINES.md) decides several of these: a request or
    grant belonging to someone else, and a read no grant covers, all answer 404 — the
    caller must not learn that the resource exists.
    """
    if isinstance(exc, PatientProfileNotFoundError | ClinicianProfileNotFoundError):
        return HTTPException(status_code=404, detail="Profile not found for this account.")
    if isinstance(exc, ClinicianNotActiveError):
        return HTTPException(
            status_code=403, detail="Your clinician profile is not active at its hospital."
        )
    if isinstance(exc, RequestNotFoundError):
        return HTTPException(status_code=404, detail="Access request not found.")
    if isinstance(exc, GrantNotFoundError):
        return HTTPException(status_code=404, detail="Consent grant not found.")
    if isinstance(exc, AccessDeniedError):
        # Never "forbidden": a caller without consent must not learn the record exists.
        return HTTPException(status_code=404, detail="Not found.")
    if isinstance(exc, RequestNotDecidableError):
        return HTTPException(
            status_code=409, detail=f"This request is {exc.status} and can no longer be answered."
        )
    if isinstance(exc, DuplicateDecisionError):
        return HTTPException(status_code=409, detail="This category has already been answered.")
    if isinstance(exc, DuplicateRequestCategoryError | DuplicateGrantError):
        return HTTPException(status_code=409, detail="This action has already been recorded.")
    if isinstance(exc, UnrequestedCategoryError):
        return HTTPException(
            status_code=422, detail="That category is not part of this access request."
        )
    if isinstance(exc, UnknownPatientError):
        return HTTPException(status_code=422, detail="Unknown patient Health ID.")
    if isinstance(exc, EmptyCategorySelectionError):
        return HTTPException(status_code=422, detail="Select at least one record category.")
    # Any ConsentError without a specific mapping is a server-side problem. Logged here
    # because HTTPException-shaped 500s never reach the unhandled-exception handler, so
    # this is the only place the cause is recorded (app/core/errors.py).
    logger.error("unmapped consent domain error", extra={"error_type": type(exc).__name__})
    return HTTPException(status_code=500, detail="The operation failed unexpectedly.")


def parse_cursor(cursor: str | None) -> CursorKey | None:
    """Decode an opaque pagination cursor; a forged/corrupted one is a validation error."""
    if cursor is None:
        return None
    try:
        return decode_cursor(cursor)
    except InvalidCursorError:
        raise HTTPException(status_code=422, detail="Invalid pagination cursor.") from None


@dataclass(frozen=True, slots=True)
class CategoryVocabulary:
    """One snapshot of the record-category controlled vocabulary, both directions.

    Ten rows (docs/DOMAIN_MODEL.md §1), so it is loaded whole rather than queried per code:
    one lookup serves a request that both resolves submitted codes and renders stored ids.
    """

    by_code: Mapping[str, UUID]
    by_id: Mapping[UUID, str]


class CategoryVocabularySource(Protocol):
    """How the consent boundary obtains that vocabulary. A protocol because the table
    belongs to ``records``; the adapter is supplied at startup."""

    async def load(self) -> CategoryVocabulary: ...


def resolve_category_codes(vocabulary: CategoryVocabulary, codes: Sequence[str]) -> list[UUID]:
    """Translate submitted codes into the ids the domain works in.

    Boundary translation, like ``parse_cursor``: an unknown code is malformed input, so it
    is a 422 naming the offenders rather than a domain error.
    """
    unknown = [code for code in codes if code not in vocabulary.by_code]
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"Unknown record category code(s): {', '.join(unknown)}."
        )
    return [vocabulary.by_code[code] for code in codes]


def get_request_context(request: Request) -> str | None:
    """The correlation key the audit trail records (docs/API_GUIDELINES.md: every response
    echoes ``X-Request-Id``). The service caps and sanitises it before storing."""
    context: str | None = getattr(request.state, "request_id", None)
    return context


class RecordsClinicianDirectory:
    """Adapts ``records``' published clinician projection to the shape consent declares.

    Ten lines of translation instead of a shared type, so neither module has to know the
    other's vocabulary: records answers "who is this practitioner", consent decides what
    that means.
    """

    def __init__(self, directory: records_directory.ClinicianDirectoryService) -> None:
        self._directory = directory

    async def get_by_user_id(self, user_id: UUID) -> Clinician | None:
        profile = await self._directory.get_by_user_id(user_id)
        if profile is None:
            return None
        return Clinician(
            id=profile.id, hospital_id=profile.hospital_id, is_active=profile.is_active
        )


class RecordsCategoryVocabulary:
    """Adapts ``records``' published category list into the two-way lookup the boundary
    needs. One query per request serves both resolving submitted codes and rendering
    stored ids."""

    def __init__(self, directory: records_directory.RecordCategoryDirectoryService) -> None:
        self._directory = directory

    async def load(self) -> CategoryVocabulary:
        categories = await self._directory.list_all()
        return CategoryVocabulary(
            by_code={category.code: category.id for category in categories},
            by_id={category.id: category.code for category in categories},
        )


def get_clinician_directory(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ClinicianDirectory:
    """The practitioner lookup, backed by records; tests override this dependency."""
    return RecordsClinicianDirectory(records_directory.clinician_directory(session))


def get_category_vocabulary_source(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CategoryVocabularySource:
    """The record-category vocabulary, backed by records; tests override this dependency."""
    return RecordsCategoryVocabulary(records_directory.record_category_directory(session))


async def get_category_vocabulary(
    source: Annotated[CategoryVocabularySource, Depends(get_category_vocabulary_source)],
) -> CategoryVocabulary:
    return await source.load()


def get_consent_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    clinicians: Annotated[ClinicianDirectory, Depends(get_clinician_directory)],
) -> ConsentService:
    # All repositories share the request's single session/transaction (get_db_session is
    # cached per request by FastAPI), so a use case and its audit rows commit together.
    return ConsentService(
        requests=ConsentRequestRepository(session),
        request_categories=ConsentRequestCategoryRepository(session),
        decisions=ConsentDecisionRepository(session),
        grants=ConsentGrantRepository(session),
        audit=AuditLogRepository(session),
        patients=PatientDirectoryService(PatientRepository(session)),
        clinicians=clinicians,
    )


ConsentServiceDep = Annotated[ConsentService, Depends(get_consent_service)]
CategoryVocabularyDep = Annotated[CategoryVocabulary, Depends(get_category_vocabulary)]
RequestContextDep = Annotated[str | None, Depends(get_request_context)]
