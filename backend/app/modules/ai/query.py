from collections.abc import Collection, Mapping
from datetime import UTC, datetime
from typing import Final, Protocol
from uuid import UUID

from app.modules.auth.domain import AuthenticatedUser, Role

from .citations import reconcile_citations
from .context import AssembledContext, ContextAudience, assemble_context
from .generation import AnswerGenerator, GeneratedAnswer
from .retrieval import RetrievedChunk
from .service import RetrievalScope, RetrievalVisibility

DEFAULT_EMPTY_EVIDENCE_ANSWER: Final[str] = (
    "The available medical records do not contain information regarding the requested topic."
)


class ChunkRetrieval(Protocol):
    """The retrieval ``AIQueryService`` uses — implemented by ``AIRetrievalService``.

    ``visibility`` stays required, as on the implementation: every caller chooses the policy.
    """

    async def search(
        self,
        *,
        patient_id: UUID,
        category_ids: frozenset[UUID],
        query: str,
        visibility: RetrievalVisibility,
        limit: int,
    ) -> list[RetrievedChunk]: ...


class SummaryAuditor(Protocol):
    """How AI summary generation reaches the patient's audit trail."""

    async def record_summary_generated(
        self,
        requester: AuthenticatedUser,
        *,
        patient_id: UUID,
        at: datetime,
        request_context: str | None = None,
    ) -> None: ...


class SearchAuditor(Protocol):
    """How a clinician's chunk search reaches the patient's audit trail.

    Implemented by ``ConsentService.record_search``: one scope-level event per request,
    ``RECORDS_SEARCHED`` when the clinician had a scope to search and ``ACCESS_DENIED`` when
    they had none — the one-row rule of the granted-records listing (ADR-020), with its own
    action because a search returns record text rather than a chooser.
    """

    async def record_search(
        self,
        requester: AuthenticatedUser,
        *,
        patient_id: UUID,
        granted_category_ids: frozenset[UUID],
        at: datetime,
        request_context: str | None = None,
    ) -> None: ...


class PatientIdentity(Protocol):
    """Whether a patient id names a patient — implemented by ``PatientDirectoryService``.

    Needed only to decide whether an empty-scope search can be attributed: an audit row
    references its patient, so a probe of an id that names nobody has no trail to join.
    """

    async def health_ids_by_id(self, patient_ids: Collection[UUID]) -> Mapping[UUID, str]: ...


class AIQueryService:
    """Coordinates consent scope, deterministic AI retrieval, and answer synthesis."""

    def __init__(
        self,
        retrieval: ChunkRetrieval,
        consent: RetrievalScope,
        auditor: SummaryAuditor | None = None,
        *,
        search_auditor: SearchAuditor | None = None,
        patients: PatientIdentity | None = None,
    ) -> None:
        self._retrieval = retrieval
        self._consent = consent
        self._auditor = (
            auditor
            if auditor is not None
            else (consent if hasattr(consent, "record_summary_generated") else None)
        )
        self._search_auditor = search_auditor
        self._patients = patients

    async def search_records(
        self,
        requester: AuthenticatedUser,
        *,
        patient_id: UUID,
        query: str,
        limit: int = 10,
        request_context: str | None = None,
    ) -> list[RetrievedChunk]:
        """The audited clinician search behind ``GET /ai/patients/{id}/search``.

        Returns the same chunks as ``search`` and writes exactly one audit event:

        * a non-empty consent scope → retrieval runs, then ``RECORDS_SEARCHED`` is written
          (also when nothing matched: the clinician still searched the granted scope);
        * an empty scope (no live grant, inactive clinician) → nothing is retrieved and
          ``ACCESS_DENIED`` is written, provided the id names a patient. An id that names
          nobody returns an empty list unaudited: there is no trail to attribute it to.

        Both writes share the request transaction, so a retrieval failure leaves no event
        claiming a search that returned nothing. Neither the query text nor any chunk
        content is written to the audit row or logged.
        """
        if self._search_auditor is None or self._patients is None:
            # Fail closed: an unaudited path to record text is the defect this replaces.
            raise RuntimeError("search_records requires a search auditor and patient identity")
        at = datetime.now(UTC)
        category_ids = await self._consent.granted_category_ids(
            requester, patient_id=patient_id, at=at
        )
        if not category_ids:
            if patient_id in await self._patients.health_ids_by_id([patient_id]):
                await self._search_auditor.record_search(
                    requester,
                    patient_id=patient_id,
                    granted_category_ids=category_ids,
                    at=at,
                    request_context=request_context,
                )
            return []

        chunks = await self._retrieval.search(
            patient_id=patient_id,
            category_ids=category_ids,
            query=query,
            visibility=RetrievalVisibility.GRANTEE,
            limit=limit,
        )

        # Re-check active consent after retrieval to prevent TOCTOU race:
        final_at = datetime.now(UTC)
        current_category_ids = await self._consent.granted_category_ids(
            requester, patient_id=patient_id, at=final_at
        )
        if not current_category_ids:
            if patient_id in await self._patients.health_ids_by_id([patient_id]):
                await self._search_auditor.record_search(
                    requester,
                    patient_id=patient_id,
                    granted_category_ids=frozenset(),
                    at=final_at,
                    request_context=request_context,
                )
            return []

        authorized_chunks = [c for c in chunks if c.category_id in current_category_ids]
        await self._search_auditor.record_search(
            requester,
            patient_id=patient_id,
            granted_category_ids=current_category_ids,
            at=final_at,
            request_context=request_context,
        )
        return authorized_chunks

    async def search(
        self,
        requester: AuthenticatedUser,
        *,
        patient_id: UUID,
        query: str,
        limit: int = 10,
    ) -> list[RetrievedChunk]:
        category_ids = await self._consent.granted_category_ids(
            requester,
            patient_id=patient_id,
            at=datetime.now(UTC),
        )

        return await self._retrieval.search(
            patient_id=patient_id,
            category_ids=category_ids,
            query=query,
            visibility=RetrievalVisibility.GRANTEE,
            limit=limit,
        )

    async def assemble_context(
        self,
        requester: AuthenticatedUser,
        *,
        patient_id: UUID,
        query: str,
        category_codes: Mapping[UUID, str],
        limit: int = 10,
        max_tokens: int = 1000,
    ) -> AssembledContext:
        chunks = await self.search(
            requester,
            patient_id=patient_id,
            query=query,
            limit=limit,
        )

        return assemble_context(
            query=query,
            patient_id=patient_id,
            chunks=chunks,
            category_codes=category_codes,
            max_tokens=max_tokens,
        )

    async def _synthesize_and_audit(
        self,
        context: AssembledContext,
        requester: AuthenticatedUser,
        patient_id: UUID,
        generator: AnswerGenerator,
        request_context: str | None = None,
        category_codes: Mapping[UUID, str] | None = None,
    ) -> GeneratedAnswer:
        now = datetime.now(UTC)

        # Empty-context check: do NOT call generator, do NOT write audit. A granted scope
        # that simply matched nothing is not an access to anything.
        if not context.items:
            return _empty_answer(generator, now)

        # Context has evidence: invoke generator, then hold its provenance to the evidence
        # actually supplied — markers naming nothing are removed, and only indices that appear
        # as markers in the text are returned as citations (ai/citations.py).
        generated = reconcile_citations(await generator.generate_answer(context), context)

        # For doctor answer generation, perform authoritative post-synthesis verification:
        # if any category of evidence used to construct the answer was revoked or expired
        # while the generator was running, discard the answer and citations, and record the
        # refusal (ACCESS_DENIED) rather than a summary the clinician never received.
        # Fails closed: evidence whose category cannot be mapped back to an id counts as
        # no longer authorized, so a missing vocabulary can never skip the check.
        if requester.role is Role.DOCTOR and self._consent is not None:
            code_to_id = (
                {code: uid for uid, code in category_codes.items()} if category_codes else {}
            )
            used_categories: set[UUID] = set()
            unmapped = False
            for item in context.items:
                cat_id = code_to_id.get(item.category_code)
                if cat_id is None:
                    unmapped = True
                else:
                    used_categories.add(cat_id)

            final_at = datetime.now(UTC)
            final_granted = await self._consent.granted_category_ids(
                requester, patient_id=patient_id, at=final_at
            )
            if unmapped or not used_categories.issubset(final_granted):
                await self._record_denial(
                    requester, patient_id=patient_id, at=final_at, request_context=request_context
                )
                return _empty_answer(generator, final_at)

        # Audit recording: only after successful generation
        if self._auditor is not None:
            await self._auditor.record_summary_generated(
                requester,
                patient_id=patient_id,
                at=generated.generated_at,
                request_context=request_context,
            )

        return generated

    async def _record_denial(
        self,
        requester: AuthenticatedUser,
        *,
        patient_id: UUID,
        at: datetime,
        request_context: str | None,
    ) -> None:
        """ACCESS_DENIED for a refused or discarded clinician answer, when attributable.

        Reuses the scope-event writer search uses: an empty scope is written as
        ``ACCESS_DENIED`` with no target and no query text. An id that names no patient
        has no trail to join, exactly as for search.
        """
        if self._search_auditor is None or self._patients is None:
            return
        if patient_id in await self._patients.health_ids_by_id([patient_id]):
            await self._search_auditor.record_search(
                requester,
                patient_id=patient_id,
                granted_category_ids=frozenset(),
                at=at,
                request_context=request_context,
            )

    async def generate_answer(
        self,
        requester: AuthenticatedUser,
        *,
        patient_id: UUID,
        query: str,
        category_codes: Mapping[UUID, str],
        generator: AnswerGenerator,
        limit: int = 10,
        max_tokens: int = 1000,
        request_context: str | None = None,
    ) -> GeneratedAnswer:
        """Coordinate retrieval, context assembly, and answer synthesis with audit recording.

        1. Resolves consent-authorized categories and retrieves matching chunks. An empty
           scope writes ACCESS_DENIED and returns the empty-evidence answer.
        2. Deterministically assembles context adhering to token budget.
        3. If context contains no evidence:
           - Bypasses AnswerGenerator (neither Ollama nor Fake is called).
           - Bypasses audit recording (no summary was synthesized).
           - Returns deterministic empty-evidence GeneratedAnswer immediately.
        4. If context contains evidence:
           - Invokes the injected AnswerGenerator.
           - Re-checks consent; if any evidence category was revoked meanwhile, discards
             the answer and citations and records ACCESS_DENIED instead.
           - Otherwise, only AFTER successful generation, records SUMMARY_GENERATED.
           - Returns the GeneratedAnswer.
        """
        at = datetime.now(UTC)
        category_ids = await self._consent.granted_category_ids(
            requester, patient_id=patient_id, at=at
        )
        if not category_ids:
            # No live grant (or an inactive clinician): nothing is retrieved, the generator
            # is not called, and the attempt is on the patient's trail as ACCESS_DENIED —
            # the same verdict search and export record for a refused clinician.
            await self._record_denial(
                requester, patient_id=patient_id, at=at, request_context=request_context
            )
            return _empty_answer(generator, at)

        chunks = await self._retrieval.search(
            patient_id=patient_id,
            category_ids=category_ids,
            query=query,
            visibility=RetrievalVisibility.GRANTEE,
            limit=limit,
        )
        context = assemble_context(
            query=query,
            patient_id=patient_id,
            chunks=chunks,
            category_codes=category_codes,
            max_tokens=max_tokens,
        )

        return await self._synthesize_and_audit(
            context,
            requester,
            patient_id,
            generator,
            request_context=request_context,
            category_codes=category_codes,
        )

    async def generate_self_answer(
        self,
        patient_user: AuthenticatedUser,
        *,
        patient_id: UUID,
        query: str,
        category_codes: Mapping[UUID, str],
        generator: AnswerGenerator,
        limit: int = 10,
        max_tokens: int = 1000,
        request_context: str | None = None,
    ) -> GeneratedAnswer:
        """Synthesize an answer for an authenticated patient querying their own records.

        Patient self-query bypasses doctor consent grants (patients own their records).
        Retrieval scope includes all categories in the vocabulary.
        """
        category_ids = frozenset(category_codes.keys())
        chunks = await self._retrieval.search(
            patient_id=patient_id,
            category_ids=category_ids,
            query=query,
            visibility=RetrievalVisibility.OWNER,
            limit=limit,
        )

        context = assemble_context(
            query=query,
            patient_id=patient_id,
            chunks=chunks,
            category_codes=category_codes,
            max_tokens=max_tokens,
            audience=ContextAudience.PATIENT,
        )

        return await self._synthesize_and_audit(
            context,
            patient_user,
            patient_id,
            generator,
            request_context=request_context,
        )


def _empty_answer(generator: AnswerGenerator, at: datetime) -> GeneratedAnswer:
    """The deterministic no-evidence answer, labelled with the generator it bypassed."""
    fake = "Fake" in type(generator).__name__
    provider = getattr(generator, "provider", "fake" if fake else "ollama")
    model = getattr(generator, "model", "fake-v1" if fake else "qwen3:8b")
    return GeneratedAnswer(
        answer=DEFAULT_EMPTY_EVIDENCE_ANSWER,
        citations=(),
        provider=str(provider),
        model=str(model),
        generated_at=at,
    )
