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

**Two questions, two methods.** ``enforce`` rules on one record and audits the outcome;
``granted_category_ids`` reports which categories a clinician may currently read and rules
on nothing. Keeping them apart is what lets ``records`` filter a listing without either
authorizing by the wrong route or writing a page-sized burst of audit rows (ADR-020). They
share the rules that decide them — ``_acting_clinician`` and the grant predicate in the
repository — so the two answers cannot drift apart.

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
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID, uuid4

from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.consent.errors import (
    AccessDeniedError,
    ClinicianNotActiveError,
    ClinicianProfileNotFoundError,
    EmptyCategorySelectionError,
    GrantNotFoundError,
    HospitalProfileNotFoundError,
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
from app.shared.time import utc_now

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


#: The hashing scheme of revision 0004 — ten-key canonical payload, SHA-256. Rows written
#: before migration 0005 carry it, and their digests reproduce only under it (ADR-023).
HASH_SCHEME_V1: Final = 1

#: The current scheme: the same payload plus ``actor_hospital_id``, still SHA-256. ADR-019's
#: keccak transition becomes v3 and has this mechanism to land in.
HASH_SCHEME_V2: Final = 2

#: The scheme new events are written under.
CURRENT_HASH_SCHEME: Final = HASH_SCHEME_V2


def canonical_event_payload(fields: Mapping[str, object], *, scheme: int) -> str:
    """The exact bytes a scheme hashes, for writing and for verifying alike.

    One function for both directions on purpose: a verifier that rebuilt the payload
    independently would be a second implementation of the thing it is checking, and the
    first divergence between them would look like tampering.

    **v1 omits ``actor_hospital_id`` entirely rather than emitting it as null.** That is the
    whole reason legacy rows still verify: their digests were computed over a payload in
    which the key did not exist, so re-adding it — even as null — would change the bytes and
    fail every row written before migration 0005.
    """
    payload = dict(fields)
    if scheme == HASH_SCHEME_V1:
        payload.pop("actor_hospital_id", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


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
class PersonDisplay:
    """A member of hospital staff as the patient may see them: a name, where they work,
    and a specialty when the row has one. The projection consent needs in order to render
    a requester, a grantee or an actor — nothing more."""

    full_name: str
    specialty: str | None
    hospital_name: str


class StaffDirectory(Protocol):
    """How consent turns the ids it stores into something a patient can read.

    A second protocol beside ``ClinicianDirectory`` rather than more methods on it, because
    the two answer different questions: that one decides whether someone may act, this one
    only says what to call them. Keeping them apart is what stops an authorization lookup
    from acquiring display fields, or a display lookup from acquiring employment status.

    Every method is **batched by construction** — a collection in, a mapping out. A listing
    resolves one page of identities in a fixed number of statements no matter how many rows
    it holds, and an id that resolves to nothing is simply absent from the mapping.
    """

    async def clinicians_by_id(
        self, doctor_ids: Collection[UUID]
    ) -> Mapping[UUID, PersonDisplay]: ...

    async def staff_by_user_id(
        self, user_ids: Collection[UUID]
    ) -> Mapping[UUID, PersonDisplay]: ...

    async def hospital_names(self, hospital_ids: Collection[UUID]) -> Mapping[UUID, str]: ...

    #: The scope for the hospital audit view (ADR-023). Not batched, unlike the rest: it
    #: answers a question about the caller, and there is one caller per request.
    async def administered_hospital_id(self, user_id: UUID) -> UUID | None: ...


@dataclass(frozen=True, slots=True)
class RequestView:
    """An access request with the categories it asked for. Decisions are deliberately not
    included: a listing shows status, and what a clinician may actually read is answered
    by ``enforce``, never by reading a list.

    The two display fields are populated by the listings and left empty by
    ``create_request``, whose caller is the requester and already knows who they are. Both
    are optional for the same reason every projection here is: an id that no longer
    resolves must degrade to a missing name, never to a failed request.
    """

    request: ConsentRequest
    requested_category_ids: tuple[UUID, ...]
    requester: PersonDisplay | None = None
    #: The hospital the request was raised under, which is not necessarily where the
    #: requester practises today — the request row records the affiliation at the time.
    requester_hospital_name: str | None = None
    #: Who the request is about. Populated for the clinician's own outgoing listing, where
    #: the subject is the one thing the requester cannot infer from context; left empty for
    #: the patient's inbox, where every row is about the reader.
    patient_health_id: str | None = None


@dataclass(frozen=True, slots=True)
class RequestPage:
    items: list[RequestView]
    next_cursor: str | None


class ConsentGrantState(StrEnum):
    """Whether a grant still permits a read, and if not, why not.

    **Derived, never stored.** ``ConsentRequestStatus`` and ``ConsentDecisionStatus`` are
    columns; this is a reading of the two columns enforcement itself consults, taken at a
    given instant. There is no state transition to EXPIRED — a grant simply stops being
    active when its deadline passes, which is why nothing writes this value anywhere.
    """

    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


def grant_state(grant: ConsentGrant, now: datetime) -> ConsentGrantState:
    """The same predicate ``ConsentGrantRepository.get_active`` applies, spelled out.

    Kept deliberately identical to that query (``revoked_at IS NULL AND expires_at > at``)
    so a grant this reports ACTIVE is exactly one enforcement would honour. Revocation is
    checked first because it outranks a deadline that has not yet passed.
    """
    if grant.revoked_at is not None:
        return ConsentGrantState.REVOKED
    if as_utc(grant.expires_at) <= now:
        return ConsentGrantState.EXPIRED
    return ConsentGrantState.ACTIVE


@dataclass(frozen=True, slots=True)
class GrantView:
    """A grant with the state the service read for it, so the boundary never has to
    consult a clock of its own to describe one, and the clinician it was granted to."""

    grant: ConsentGrant
    state: ConsentGrantState
    grantee: PersonDisplay | None = None


@dataclass(frozen=True, slots=True)
class GrantPage:
    items: list[GrantView]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class AuditView:
    """One trail entry with the actor's name, where this module knows one.

    ``actor`` is empty for the patient's own actions and for any account that is not
    hospital staff: the role on the entry already says who acted, and inventing a label for
    "you" is the reader's job, not the API's.
    """

    entry: AuditLog
    actor: PersonDisplay | None


@dataclass(frozen=True, slots=True)
class AuditPage:
    items: list[AuditView]
    next_cursor: str | None


def _row_created_at(row: ConsentRequest | ConsentGrant) -> CursorKey:
    """Keyset position for the listings ordered by when the row was written."""
    return CursorKey(created_at=row.created_at, item_id=row.id)


def _row_occurred_at(row: AuditLog) -> CursorKey:
    """Keyset position for the trail, which is ordered by the application-assigned event
    time rather than the row's storage timestamp — the column
    ``ix_audit_logs_patient_id_occurred_at_id`` covers and the one the hash protects.
    ``CursorKey`` names its first member ``created_at``; the cursor is opaque, and the
    repository applies it to whichever column that listing sorts on."""
    return CursorKey(created_at=row.occurred_at, item_id=row.id)


def _split_page[Row](
    rows: list[Row], *, limit: int, key: Callable[[Row], CursorKey]
) -> tuple[list[Row], str | None]:
    """Turn a ``limit + 1`` fetch into one page and the cursor that continues it.

    Every keyset listing asks its repository for one row more than the caller wanted; this
    is the single place that extra row is interpreted, so "is there a next page" and "what
    does its cursor say" cannot drift apart between them. ``key`` is what varies: which
    column a listing is ordered by is the caller's fact, not this helper's.
    """
    has_more = len(rows) > limit
    page = rows[:limit]
    if not has_more:
        return page, None
    return page, encode_cursor(key(page[-1]))


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
        staff: StaffDirectory,
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
        self._staff = staff
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
            actor_hospital_id=clinician.hospital_id,
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
        # One statement for the whole page: the subject of each request, by Health ID.
        # The clinician typed it to raise the request, so this returns it to them and
        # nothing else off the patient row (patients.directory).
        health_ids = await self._patients.health_ids_by_id({row.patient_id for row in rows})
        return await self._to_page(rows, limit=limit, patient_health_ids=health_ids)

    # -- grants ------------------------------------------------------------------------

    async def list_grants(
        self, caller: AuthenticatedUser, *, after: CursorKey | None, limit: int
    ) -> GrantPage:
        """Every grant ever derived for this patient, newest first, with its current state.

        The patient's history, not the enforcement view: revoked and expired grants stay in
        the list because withdrawing access is a fact the owner is entitled to see, and
        because "who could read this last month" is the question the page exists to answer.
        The repository already draws that distinction, so this method adds only the scope
        (the caller's own patient row, taken from the token) and the state reading.

        Each state is read once, from this service's clock, so every row in a page is
        described as of the same instant.
        """
        patient = await self._patients.get_by_user_id(caller.user_id)
        if patient is None:
            raise PatientProfileNotFoundError()
        rows = await self._grants.list_page_by_patient(patient.id, after=after, limit=limit + 1)
        page, next_cursor = _split_page(rows, limit=limit, key=_row_created_at)
        now = self._now()
        grantees = await self._staff.clinicians_by_id({row.grantee_doctor_id for row in page})
        return GrantPage(
            items=[
                GrantView(
                    grant=row,
                    state=grant_state(row, now),
                    grantee=grantees.get(row.grantee_doctor_id),
                )
                for row in page
            ],
            next_cursor=next_cursor,
        )

    # -- the trail ---------------------------------------------------------------------

    async def list_audit_events(
        self, caller: AuthenticatedUser, *, after: CursorKey | None, limit: int
    ) -> AuditPage:
        """The patient's own audit trail, most recent event first.

        The subject's view of an append-only log: every consent decision, every revocation,
        every read of their records — including the refusals, which is the property the M3
        gate exists to guarantee (.claude/ROADMAP.md). Scope comes from the token; the
        ``patient_id`` column is what makes the log patient-visible in the first place
        (docs/DOMAIN_MODEL.md §1), and no caller can widen it.

        Reading the trail writes nothing to it. An audit log that recorded its own reads
        would grow without bound and would say nothing about access to records, which is
        what it is for.
        """
        patient = await self._patients.get_by_user_id(caller.user_id)
        if patient is None:
            raise PatientProfileNotFoundError()
        rows = await self._audit.list_page_by_patient(patient.id, after=after, limit=limit + 1)
        page, next_cursor = _split_page(rows, limit=limit, key=_row_occurred_at)
        actors = await self._staff.staff_by_user_id({row.actor_user_id for row in page})
        return AuditPage(
            items=[AuditView(entry=row, actor=actors.get(row.actor_user_id)) for row in page],
            next_cursor=next_cursor,
        )

    async def list_hospital_audit_events(
        self, caller: AuthenticatedUser, *, after: CursorKey | None, limit: int
    ) -> AuditPage:
        """One hospital's own activity, most recent event first (ADR-023).

        The organisation's view of the same append-only log the patient reads, filtered to
        the events its own staff generated. Scope comes from the token — the caller's admin
        profile decides the hospital, and there is no parameter that could name another one.

        **Attribution is historical.** The filter reads ``actor_hospital_id`` as recorded
        when each event was written, so a clinician who transfers hospitals does not carry
        their history with them, and a hospital cannot acquire events by hiring.

        Two absences are by design and not worth hiding: patient-actor events have no
        hospital, and every event written before migration 0005 is unattributed. The second
        is a real blind spot — pre-migration activity is not shown, because the only way to
        infer it would be the present-affiliation join this design exists to refuse.

        Reading the trail writes nothing to it, exactly as for the patient's view.
        """
        hospital_id = await self._staff.administered_hospital_id(caller.user_id)
        if hospital_id is None:
            raise HospitalProfileNotFoundError()
        rows = await self._audit.list_page_by_hospital(hospital_id, after=after, limit=limit + 1)
        page, next_cursor = _split_page(rows, limit=limit, key=_row_occurred_at)
        actors = await self._staff.staff_by_user_id({row.actor_user_id for row in page})
        return AuditPage(
            items=[AuditView(entry=row, actor=actors.get(row.actor_user_id)) for row in page],
            next_cursor=next_cursor,
        )

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
        allowed, clinician = await self._decide_read(
            requester, patient_id=patient_id, category_id=category_id
        )
        await self._write_audit(
            requester,
            action=action if allowed else AuditAction.ACCESS_DENIED,
            patient_id=patient_id,
            target_record_id=record_id,
            target_category_id=category_id,
            occurred_at=now,
            request_context=request_context,
            # The clinician's hospital when they acted; None for a patient reading their own
            # records, and None for a refused caller who is no clinician at all (ADR-023).
            actor_hospital_id=clinician.hospital_id if clinician is not None else None,
        )
        if not allowed:
            raise AccessDeniedError()

    async def granted_category_ids(
        self, requester: AuthenticatedUser, *, patient_id: UUID, at: datetime
    ) -> frozenset[UUID]:
        """Every category of this patient's records the requester may currently read.

        The **scope** question, as distinct from ``enforce``'s **verdict** question, and
        the seam ``records`` uses to filter a clinician's listing (ADR-020). Side-effect
        free by construction: it authorizes nothing, refuses nothing, and writes no audit
        row, which is what makes it safe to call before knowing whether a listing will even
        be served — and what will let M5's consent-scoped retrieval reuse it.

        It shares the two rules that decide ``enforce`` rather than restating them: the
        ADR-015 acting-clinician test below, and the grant predicate inside
        ``list_active_category_ids``. A category in this set is therefore exactly a
        category ``enforce`` would admit at the same instant, so a record surfaced by a
        listing cannot be one a subsequent read refuses (barring a change between the two
        calls, which is revocation working).

        Anyone who is not an acting clinician has an empty scope — patients included: a
        patient's own records are reached by ownership, never by a grant, and no caller
        should be able to obtain a "scope" for someone else's data by asking nicely.
        """
        clinician = await self._acting_clinician(requester)
        if clinician is None:
            return frozenset()
        return frozenset(
            await self._grants.list_active_category_ids(
                patient_id=patient_id, grantee_doctor_id=clinician.id, at=at
            )
        )

    async def record_upload(
        self,
        actor: AuthenticatedUser,
        *,
        patient_id: UUID,
        record_id: UUID,
        actor_hospital_id: UUID | None = None,
        request_context: str | None = None,
    ) -> None:
        """Append the ``RECORD_UPLOADED`` event for one stored document (M3-B, ADR-022).

        ``RECORD_UPLOADED`` has been in docs/DOMAIN_MODEL.md §1's vocabulary since M0.2 and
        in ``AuditAction`` since M3, and nothing wrote it: a document could enter a
        patient's history leaving no trace of who put it there. This is the writer.

        Audit metadata only — who, for whom, which record, when. No filename, no category
        beyond the record reference, and nothing of the document itself: the trail says an
        upload happened, not what was in it.
        """
        await self._write_audit(
            actor,
            action=AuditAction.RECORD_UPLOADED,
            patient_id=patient_id,
            target_record_id=record_id,
            occurred_at=self._now(),
            request_context=request_context,
            actor_hospital_id=actor_hospital_id,
        )

    async def record_direct_read(
        self,
        actor: AuthenticatedUser,
        *,
        patient_id: UUID,
        record_id: UUID,
        action: AuditAction,
        allowed: bool,
        actor_hospital_id: UUID | None = None,
        request_context: str | None = None,
    ) -> None:
        """Append the event for a read authorized by a *relationship* rather than a grant.

        The hospital-admin own-upload path (ADR-013 layer 2) never reaches ``enforce``,
        because only ``records`` can evaluate "did my hospital upload this" — so until
        ADR-022 that whole path, allowed and refused alike, wrote nothing. That was finding
        M3-E, and the asymmetry it created was indefensible: a clinician's refused read was
        on the patient's trail and a hospital's was not.

        This does not decide anything. ``records`` has already ruled; this records the
        ruling it made, which is why the outcome arrives as ``allowed`` rather than being
        recomputed here. A refusal is written as ``ACCESS_DENIED`` on the same terms
        ADR-018 set for clinicians.
        """
        await self._write_audit(
            actor,
            action=action if allowed else AuditAction.ACCESS_DENIED,
            patient_id=patient_id,
            target_record_id=record_id,
            occurred_at=self._now(),
            request_context=request_context,
            actor_hospital_id=actor_hospital_id,
        )

    async def record_listing(
        self,
        requester: AuthenticatedUser,
        *,
        patient_id: UUID,
        granted_category_ids: frozenset[UUID],
        at: datetime,
        request_context: str | None = None,
    ) -> None:
        """Append the single audit event for one clinician listing (ADR-020).

        Separate from ``granted_category_ids`` because a scope query must stay free of
        side effects and this is nothing but a side effect; separate from ``enforce``
        because that call authorizes one record and this one authorizes nothing at all —
        by the time it runs the ruling has been made, and its job is only to make the
        ruling visible to the patient.

        **Exactly one row, whatever the page holds.** A listing is one act by one
        clinician; writing a row per record would assert reads that never happened, bury
        the patient's trail under a page-sized burst, and cost a chain anchor apiece at M6
        (ADR-004). What was actually read stays fully traceable, because opening any of
        those records still writes its own ``RECORD_VIEWED``.

        An empty scope is a refusal, not a quiet nothing: a clinician with no live grant
        who asks what they may read has been told "nothing", and the patient is entitled to
        see that they asked. Which action is written is decided here rather than by the
        caller — the vocabulary belongs to this module.
        """
        # Resolved here rather than passed in: `records` knows the caller is a clinician but
        # not which hospital they act for, and ADR-016 keeps that projection on this side.
        listing_clinician = await self._acting_clinician(requester)
        await self._write_audit(
            requester,
            action=(
                AuditAction.RECORDS_LISTED if granted_category_ids else AuditAction.ACCESS_DENIED
            ),
            patient_id=patient_id,
            occurred_at=at,
            request_context=request_context,
            actor_hospital_id=listing_clinician.hospital_id
            if listing_clinician is not None
            else None,
        )

    async def _acting_clinician(self, requester: AuthenticatedUser) -> Clinician | None:
        """The requester as a practitioner who may act clinically, or None.

        ADR-015 in one place: a suspended clinician loses access even where a grant
        survives. Shared by the verdict path and the scope path so the suspension rule
        cannot come to mean two different things.
        """
        if requester.role is not Role.DOCTOR:
            return None
        clinician = await self._clinicians.get_by_user_id(requester.user_id)
        return clinician if clinician is not None and clinician.is_active else None

    async def _decide_read(
        self, requester: AuthenticatedUser, *, patient_id: UUID, category_id: UUID
    ) -> tuple[bool, Clinician | None]:
        """The verdict, and the clinician it was decided about.

        Returns the practitioner as well as the answer so ``enforce`` can attribute the
        audit row to the hospital they were acting for (ADR-023) without resolving them a
        second time — and, more importantly, without resolving them *later*, which is the
        join that would move history when staff transfer.
        """
        if requester.role is Role.PATIENT:
            patient = await self._patients.get_by_user_id(requester.user_id)
            return (patient is not None and patient.id == patient_id), None
        clinician = await self._acting_clinician(requester)
        if clinician is None:
            return False, None
        grant = await self._grants.get_active(
            patient_id=patient_id,
            grantee_doctor_id=clinician.id,
            category_id=category_id,
            at=self._now(),
        )
        return grant is not None, clinician

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

    async def _to_page(
        self,
        rows: list[ConsentRequest],
        *,
        limit: int,
        patient_health_ids: Mapping[UUID, str] | None = None,
    ) -> RequestPage:
        """The shared listing projection. ``patient_health_ids`` is supplied only by the
        clinician's own listing; the inbox passes nothing, so its rows carry no subject and
        its response shape is unchanged."""
        page, next_cursor = _split_page(rows, limit=limit, key=_row_created_at)
        # Two statements for the whole page, whatever its size — see StaffDirectory.
        requesters = await self._staff.clinicians_by_id({row.requester_doctor_id for row in page})
        hospitals = await self._staff.hospital_names({row.requester_hospital_id for row in page})
        items = [
            RequestView(
                request=row,
                requested_category_ids=tuple(
                    entry.category_id
                    for entry in await self._request_categories.list_by_request(row.id)
                ),
                requester=requesters.get(row.requester_doctor_id),
                requester_hospital_name=hospitals.get(row.requester_hospital_id),
                patient_health_id=(
                    None if patient_health_ids is None else patient_health_ids.get(row.patient_id)
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
        actor_hospital_id: UUID | None = None,
    ) -> AuditLog:
        """Append one audit event, hashed, in the caller's transaction.

        The row id and ``occurred_at`` are assigned here so the canonical payload is
        complete before the INSERT — the reason ``event_hash`` is computable at all without
        the second write append-only forbids (app/modules/consent/models.py).

        ``actor_hospital_id`` is the hospital the actor was acting for **at this moment**
        (ADR-023). It arrives as an argument rather than being looked up here, because a
        lookup would necessarily read the actor's *current* affiliation and so would rewrite
        history the first time a doctor changed hospitals. ``None`` is the honest value for
        a patient actor, who has no hospital at all.
        """
        event_id = uuid4()
        context = self._normalize_context(request_context)
        payload: dict[str, object] = {
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
            "actor_hospital_id": str(actor_hospital_id) if actor_hospital_id else None,
        }
        canonical = canonical_event_payload(payload, scheme=CURRENT_HASH_SCHEME)
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
                actor_hospital_id=actor_hospital_id,
                request_context=context,
                occurred_at=occurred_at,
                event_hash=self._hash(canonical),
                hash_version=CURRENT_HASH_SCHEME,
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
