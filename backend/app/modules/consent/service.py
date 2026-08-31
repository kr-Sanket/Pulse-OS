"""consent domain logic: the request → decision → grant → revocation lifecycle, and the
single enforcement point every non-owner record read passes through.

Framework-free and owning no transaction, like the other modules' services: collaborators
arrive through the constructor and the request scope commits (app/core/db.py). Nothing here
imports FastAPI, touches a session, or calls ``commit`` — repositories flush, the request
commits, and a failure anywhere rolls the whole use case back. That is what makes the
audit guarantee below structural rather than aspirational.

**Every state change writes its audit event in the same transaction as the change**
(docs/DOMAIN_MODEL.md §1, .claude/CHECKLIST.md): a request, each per-category decision,
each revocation, every allowed read, and every denied read. There is no code path that
mutates consent state without appending to the trail, because the audit write happens in
the same private helper that performs the change.

**``enforce`` is ADR-013 layer 3 and nothing else.** Layer 1 (role gates) belongs to the
router and layer 2 (relationship checks — a hospital reading its own upload) belongs to
``records``; this service is consulted when those do not already settle the question. The
one relationship it does resolve itself is the patient's own data, because
docs/SYSTEM_ARCHITECTURE.md rule 3 requires that case to pass trivially *and still log*.

**Cross-module reads go through published interfaces only.** Patients are resolved through
``patients.directory``; clinicians through the ``ClinicianDirectory`` protocol below,
because ``records`` publishes no equivalent seam today. Record categories are opaque UUIDs
here: the boundary resolves codes against the records vocabulary before calling, and the
composite foreign key on ``consent_decisions`` is what keeps a decision tied to a category
the request actually asked for.
"""

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol
from uuid import UUID, uuid4

from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.consent.errors import (
    AccessDeniedError,
    ClinicianNotActiveError,
    ClinicianProfileNotFoundError,
    EmptyCategorySelectionError,
    GrantNotFoundError,
    PatientProfileNotFoundError,
    RequestNotDecidableError,
    RequestNotFoundError,
    UnknownPatientError,
)
from app.modules.consent.models import (
    AuditAction,
    AuditLog,
    ConsentDecision,
    ConsentDecisionStatus,
    ConsentGrant,
    ConsentRequest,
    ConsentRequestCategory,
    ConsentRequestStatus,
)
from app.modules.consent.repository import (
    AuditLogRepository,
    ConsentDecisionRepository,
    ConsentGrantRepository,
    ConsentRequestCategoryRepository,
    ConsentRequestRepository,
)
from app.modules.patients.directory import PatientDirectoryService
from app.shared.pagination import CursorKey, encode_cursor

#: Undecided requests lapse after this long (docs/DOMAIN_MODEL.md §1 design default).
DEFAULT_REQUEST_TTL: Final = timedelta(days=7)

#: How long an approval grants access for. OD-2 is the open decision that fixes this and
#: whether the patient may adjust it at approval time (docs/DOMAIN_MODEL.md §5); until it
#: is signed off this is the documented recommendation, injected rather than hard-coded.
DEFAULT_GRANT_TTL: Final = timedelta(days=90)

#: Cap for the persisted correlation key. ``audit_logs.request_context`` is unbounded TEXT
#: so that an oversized client ``X-Request-Id`` can never fail the audit INSERT and roll
#: back the action it records; bounding it is this layer's half of that fix, promised in
#: the module docstring of app/modules/consent/__init__.py.
MAX_REQUEST_CONTEXT: Final = 200

_UNSAFE_CONTEXT_CHARS: Final = re.compile(r"[^\x20-\x7e]+")


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Force a persisted timestamp to be timezone-aware before comparing it with the clock.

    Backends disagree: Postgres ``timestamptz`` round-trips aware, SQLite returns naive for
    the same column. Comparing a naive value with an aware ``now()`` raises ``TypeError``,
    so a deadline check that works in production would fail in the SQLite harness — the
    same class of divergence recorded for keyset cursors in app/core/db.py. Stored values
    are always UTC (the columns are ``DateTime(timezone=True)`` and the service only ever
    writes ``utc_now()``-derived instants), so attaching UTC restores the truth rather than
    guessing at it.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def sha256_event_hash(canonical_json: str) -> str:
    """Default digest for an audit event.

    ADR-004 specifies **keccak256** of the canonical event JSON, because that is what the
    Polygon anchor verifies on-chain. The project has no keccak dependency (hashlib ships
    NIST SHA-3, which is a different padding), so this default is sha256 and the real
    hasher is injected. M6 must supply the keccak implementation through that seam
    **before any anchored data exists**: changing the algorithm invalidates every digest
    already stored, and the audit table is append-only.
    """
    return hashlib.sha256(canonical_json.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Clinician:
    """The projection of a practitioner this module needs — id, affiliation, and whether
    they may act clinically. Not a copy of ``records``' Doctor row; the same relationship
    ``AuthenticatedUser`` has to auth's User."""

    id: UUID
    hospital_id: UUID
    is_active: bool


class ClinicianDirectory(Protocol):
    """How consent resolves a caller to a practitioner.

    A protocol rather than a concrete import because ``records`` currently owns Doctor but
    publishes no directory service for it (``patients`` publishes one, which is why the
    patient side is a plain import). If practitioners ever move out of ``records``, this is
    the seam that survives the move unchanged.
    """

    async def get_by_user_id(self, user_id: UUID) -> Clinician | None: ...


@dataclass(frozen=True, slots=True)
class RequestView:
    """An access request with the categories it asked for. Decisions are deliberately not
    included: a listing shows status, and what a clinician may actually read is answered
    by ``enforce``, never by reading a list."""

    request: ConsentRequest
    requested_category_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class RequestPage:
    items: list[RequestView]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class DecisionOutcome:
    """What one approve/reject call produced. ``grants`` is empty for a rejection."""

    request: ConsentRequest
    decisions: tuple[ConsentDecision, ...]
    grants: tuple[ConsentGrant, ...]


class ConsentService:
    def __init__(
        self,
        requests: ConsentRequestRepository,
        request_categories: ConsentRequestCategoryRepository,
        decisions: ConsentDecisionRepository,
        grants: ConsentGrantRepository,
        audit: AuditLogRepository,
        patients: PatientDirectoryService,
        clinicians: ClinicianDirectory,
        *,
        request_ttl: timedelta = DEFAULT_REQUEST_TTL,
        grant_ttl: timedelta = DEFAULT_GRANT_TTL,
        clock: Callable[[], datetime] = utc_now,
        event_hasher: Callable[[str], str] = sha256_event_hash,
    ) -> None:
        self._requests = requests
        self._request_categories = request_categories
        self._decisions = decisions
        self._grants = grants
        self._audit = audit
        self._patients = patients
        self._clinicians = clinicians
        self._request_ttl = request_ttl
        self._grant_ttl = grant_ttl
        self._now = clock
        self._hash = event_hasher

    # -- requests ----------------------------------------------------------------------

    async def create_request(
        self,
        caller: AuthenticatedUser,
        *,
        patient_health_id: str,
        category_ids: Sequence[UUID],
        purpose: str,
        request_context: str | None = None,
    ) -> RequestView:
        """An ACTIVE clinician asks a patient for access to a set of categories.

        The patient is named by Health ID, as they would be at a reception desk. Consent is
        per category (ADR-013), so an empty selection is refused rather than treated as
        "everything".
        """
        clinician = await self._require_active_clinician(caller)
        wanted = self._unique_categories(category_ids)
        patient = await self._patients.get_by_health_id(patient_health_id)
        if patient is None:
            raise UnknownPatientError()

        now = self._now()
        request = await self._requests.add(
            ConsentRequest(
                patient_id=patient.id,
                requester_doctor_id=clinician.id,
                requester_hospital_id=clinician.hospital_id,
                purpose=purpose,
                status=ConsentRequestStatus.PENDING,
                expires_at=now + self._request_ttl,
            )
        )
        for category_id in wanted:
            await self._request_categories.add(
                ConsentRequestCategory(request_id=request.id, category_id=category_id)
            )
        await self._write_audit(
            caller,
            action=AuditAction.ACCESS_REQUESTED,
            patient_id=patient.id,
            target_request_id=request.id,
            occurred_at=now,
            request_context=request_context,
        )
        return RequestView(request=request, requested_category_ids=wanted)

    async def list_inbox(
        self, caller: AuthenticatedUser, *, after: CursorKey | None, limit: int
    ) -> RequestPage:
        """The patient's consent inbox: requests naming them, newest first."""
        patient = await self._patients.get_by_user_id(caller.user_id)
        if patient is None:
            raise PatientProfileNotFoundError()
        rows = await self._requests.list_page_by_patient(patient.id, after=after, limit=limit + 1)
        return await self._to_page(rows, limit=limit)

    async def list_sent_requests(
        self, caller: AuthenticatedUser, *, after: CursorKey | None, limit: int
    ) -> RequestPage:
        """The clinician's own outgoing requests, newest first. Readable by a non-ACTIVE
        clinician: seeing what you asked for is not a clinical capability."""
        clinician = await self._require_clinician(caller)
        rows = await self._requests.list_page_by_requester(
            clinician.id, after=after, limit=limit + 1
        )
        return await self._to_page(rows, limit=limit)

    # -- decisions ---------------------------------------------------------------------

    async def approve_categories(
        self,
        caller: AuthenticatedUser,
        request_id: UUID,
        category_ids: Sequence[UUID],
        *,
        grant_ttl: timedelta | None = None,
        request_context: str | None = None,
    ) -> DecisionOutcome:
        """The patient approves some of the requested categories.

        Each approval writes an immutable decision AND the grant derived from it, so
        enforcement never has to replay history (docs/DATABASE_DESIGN.md §Modeling Rules).
        ``grant_ttl`` overrides the configured default — the patient-adjustable expiry
        DOMAIN_MODEL describes, pending OD-2.
        """
        return await self._decide(
            caller,
            request_id,
            category_ids,
            status=ConsentDecisionStatus.APPROVED,
            grant_ttl=grant_ttl or self._grant_ttl,
            request_context=request_context,
        )

    async def reject_categories(
        self,
        caller: AuthenticatedUser,
        request_id: UUID,
        category_ids: Sequence[UUID],
        *,
        request_context: str | None = None,
    ) -> DecisionOutcome:
        """The patient refuses some of the requested categories. A rejection is recorded
        as permanently as an approval and spawns no grant."""
        return await self._decide(
            caller,
            request_id,
            category_ids,
            status=ConsentDecisionStatus.REJECTED,
            grant_ttl=None,
            request_context=request_context,
        )

    async def revoke_grant(
        self,
        caller: AuthenticatedUser,
        grant_id: UUID,
        *,
        request_context: str | None = None,
    ) -> ConsentGrant:
        """The patient withdraws a grant. Takes effect for the very next ``enforce`` —
        there is no cache and no grace period.

        Idempotent: revoking an already-revoked grant returns it unchanged and writes no
        second audit event, because nothing changed and the trail records changes.
        """
        grant = await self._grants.get_by_id(grant_id)
        patient = await self._patients.get_by_user_id(caller.user_id)
        if patient is None:
            raise PatientProfileNotFoundError()
        # Another patient's grant is indistinguishable from a nonexistent one.
        if grant is None or grant.patient_id != patient.id:
            raise GrantNotFoundError()
        if grant.revoked_at is not None:
            return grant

        now = self._now()
        grant.revoked_at = now
        await self._write_audit(
            caller,
            action=AuditAction.CONSENT_REVOKED,
            patient_id=grant.patient_id,
            target_category_id=grant.category_id,
            occurred_at=now,
            request_context=request_context,
        )
        return grant

    # -- enforcement (ADR-013 layer 3) --------------------------------------------------

    async def enforce(
        self,
        requester: AuthenticatedUser,
        *,
        patient_id: UUID,
        category_id: UUID,
        action: AuditAction,
        record_id: UUID | None = None,
        request_context: str | None = None,
    ) -> None:
        """Authorize one read of record content and record that it happened.

        The single choke point of docs/SYSTEM_ARCHITECTURE.md rule 3: allowed or denied,
        an audit event is written either way, in the caller's transaction. Returns None on
        success and raises ``AccessDeniedError`` on refusal — never a boolean, so a caller
        cannot proceed by ignoring the result.

        Who passes: the patient themselves, trivially (their own data — still logged); an
        ACTIVE clinician holding an unrevoked, unexpired grant for this exact
        (patient, requester, category). Everyone else is refused, including SYSTEM_ADMIN,
        for whom no grant can exist (docs/SECURITY.md: no admin break-glass).
        """
        now = self._now()
        allowed = await self._is_allowed(requester, patient_id=patient_id, category_id=category_id)
        await self._write_audit(
            requester,
            action=action if allowed else AuditAction.ACCESS_DENIED,
            patient_id=patient_id,
            target_record_id=record_id,
            target_category_id=category_id,
            occurred_at=now,
            request_context=request_context,
        )
        if not allowed:
            raise AccessDeniedError()

    async def _is_allowed(
        self, requester: AuthenticatedUser, *, patient_id: UUID, category_id: UUID
    ) -> bool:
        if requester.role is Role.PATIENT:
            patient = await self._patients.get_by_user_id(requester.user_id)
            return patient is not None and patient.id == patient_id
        if requester.role is Role.DOCTOR:
            clinician = await self._clinicians.get_by_user_id(requester.user_id)
            if clinician is None or not clinician.is_active:
                # A suspended clinician loses access even where a grant survives (ADR-015).
                return False
            grant = await self._grants.get_active(
                patient_id=patient_id,
                grantee_doctor_id=clinician.id,
                category_id=category_id,
                at=self._now(),
            )
            return grant is not None
        return False

    # -- internals ---------------------------------------------------------------------

    async def _decide(
        self,
        caller: AuthenticatedUser,
        request_id: UUID,
        category_ids: Sequence[UUID],
        *,
        status: ConsentDecisionStatus,
        grant_ttl: timedelta | None,
        request_context: str | None,
    ) -> DecisionOutcome:
        wanted = self._unique_categories(category_ids)
        request = await self._require_own_open_request(caller, request_id)
        now = self._now()

        decisions: list[ConsentDecision] = []
        grants: list[ConsentGrant] = []
        for category_id in wanted:
            decision = await self._decisions.add(
                ConsentDecision(request_id=request.id, category_id=category_id, status=status)
            )
            decisions.append(decision)
            if grant_ttl is not None:
                grants.append(
                    await self._grants.add(
                        ConsentGrant(
                            decision_id=decision.id,
                            patient_id=request.patient_id,
                            grantee_doctor_id=request.requester_doctor_id,
                            category_id=category_id,
                            expires_at=now + grant_ttl,
                        )
                    )
                )
            await self._write_audit(
                caller,
                action=(
                    AuditAction.CONSENT_APPROVED
                    if status is ConsentDecisionStatus.APPROVED
                    else AuditAction.CONSENT_REJECTED
                ),
                patient_id=request.patient_id,
                target_category_id=category_id,
                target_request_id=request.id,
                occurred_at=now,
                request_context=request_context,
            )

        await self._close_request_if_fully_decided(request)
        return DecisionOutcome(request=request, decisions=tuple(decisions), grants=tuple(grants))

    async def _close_request_if_fully_decided(self, request: ConsentRequest) -> None:
        """A request is DECIDED once every category it asked for has an answer — approving
        some and rejecting others still closes it."""
        asked = {
            row.category_id for row in await self._request_categories.list_by_request(request.id)
        }
        answered = {row.category_id for row in await self._decisions.list_by_request(request.id)}
        if asked and asked <= answered:
            request.status = ConsentRequestStatus.DECIDED

    async def _require_own_open_request(
        self, caller: AuthenticatedUser, request_id: UUID
    ) -> ConsentRequest:
        """The caller's own request, still open to decisions.

        Expiry is applied lazily here as well as by any sweep: a request read after its
        deadline is closed on the spot, so a late decision can never slip through between
        sweeps.
        """
        patient = await self._patients.get_by_user_id(caller.user_id)
        if patient is None:
            raise PatientProfileNotFoundError()
        request = await self._requests.get_by_id(request_id)
        # Another patient's request must be indistinguishable from a nonexistent one.
        if request is None or request.patient_id != patient.id:
            raise RequestNotFoundError()
        if request.status is not ConsentRequestStatus.PENDING:
            raise RequestNotDecidableError(request.status.value)
        if self._now() >= as_utc(request.expires_at):
            request.status = ConsentRequestStatus.EXPIRED
            raise RequestNotDecidableError(ConsentRequestStatus.EXPIRED.value)
        return request

    async def _require_clinician(self, caller: AuthenticatedUser) -> Clinician:
        clinician = await self._clinicians.get_by_user_id(caller.user_id)
        if clinician is None:
            raise ClinicianProfileNotFoundError()
        return clinician

    async def _require_active_clinician(self, caller: AuthenticatedUser) -> Clinician:
        clinician = await self._require_clinician(caller)
        if not clinician.is_active:
            raise ClinicianNotActiveError()
        return clinician

    @staticmethod
    def _unique_categories(category_ids: Sequence[UUID]) -> tuple[UUID, ...]:
        """De-duplicate while preserving order. Category ids are opaque here — the boundary
        resolves and validates codes against the records vocabulary before calling."""
        seen: dict[UUID, None] = dict.fromkeys(category_ids)
        if not seen:
            raise EmptyCategorySelectionError()
        return tuple(seen)

    async def _to_page(self, rows: list[ConsentRequest], *, limit: int) -> RequestPage:
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = None
        if has_more:
            last = page[-1]
            next_cursor = encode_cursor(CursorKey(created_at=last.created_at, item_id=last.id))
        items = [
            RequestView(
                request=row,
                requested_category_ids=tuple(
                    entry.category_id
                    for entry in await self._request_categories.list_by_request(row.id)
                ),
            )
            for row in page
        ]
        return RequestPage(items=items, next_cursor=next_cursor)

    async def _write_audit(
        self,
        actor: AuthenticatedUser,
        *,
        action: AuditAction,
        patient_id: UUID,
        occurred_at: datetime,
        target_record_id: UUID | None = None,
        target_category_id: UUID | None = None,
        target_request_id: UUID | None = None,
        request_context: str | None = None,
    ) -> AuditLog:
        """Append one audit event, hashed, in the caller's transaction.

        The row id and ``occurred_at`` are assigned here so the canonical payload is
        complete before the INSERT — the reason ``event_hash`` is computable at all without
        the second write append-only forbids (app/modules/consent/models.py).
        """
        event_id = uuid4()
        context = self._normalize_context(request_context)
        payload = {
            "id": str(event_id),
            "actor_user_id": str(actor.user_id),
            "actor_role": actor.role.value,
            "action": action.value,
            "patient_id": str(patient_id),
            "target_record_id": str(target_record_id) if target_record_id else None,
            "target_category_id": str(target_category_id) if target_category_id else None,
            "target_request_id": str(target_request_id) if target_request_id else None,
            "request_context": context,
            "occurred_at": occurred_at.isoformat(),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return await self._audit.add(
            AuditLog(
                id=event_id,
                actor_user_id=actor.user_id,
                actor_role=actor.role,
                action=action,
                patient_id=patient_id,
                target_record_id=target_record_id,
                target_category_id=target_category_id,
                target_request_id=target_request_id,
                request_context=context,
                occurred_at=occurred_at,
                event_hash=self._hash(canonical),
            )
        )

    @staticmethod
    def _normalize_context(request_context: str | None) -> str | None:
        """Bound and sanitise the correlation key before it is stored.

        ``X-Request-Id`` is client-supplied and unvalidated (app/core/middleware.py). The
        column is unbounded so an oversized header can never fail the audit INSERT and roll
        back the action it records; this is the other half of that fix — control characters
        out, length capped, empty becomes absent.
        """
        if request_context is None:
            return None
        cleaned = _UNSAFE_CONTEXT_CHARS.sub("", request_context).strip()[:MAX_REQUEST_CONTEXT]
        return cleaned or None
