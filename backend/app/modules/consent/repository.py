"""Persistence for consent-owned tables. Pure persistence — no business rules here.

Conventions inherited from the auth, patients and records modules: a repository takes an
``AsyncSession``, never commits (the request scope owns the transaction, app/core/db.py),
flushes inside a savepoint wherever a unique constraint doubles as a domain check, and
translates ``IntegrityError`` into a consent domain error so services never touch
SQLAlchemy session details.

Two module-specific rules:

- **No query here joins another module's tables.** Doctors, hospitals and record
  categories are referenced by UUID only; the display context an inbox needs is assembled
  by the service through the owning modules' published interfaces
  (docs/SYSTEM_ARCHITECTURE.md rule 1). That is why every method below returns consent
  entities rather than the joined tuples app/modules/records/repository.py builds — records
  owns the tables it joins, and consent owns none of them.
- **Append-only tables get insert and read methods only.** There is no update or delete for
  ``ConsentRequestCategory``, ``ConsentDecision`` or ``AuditLog``
  (docs/DATABASE_DESIGN.md principle 3, ADR-004). ``ConsentRequest.status`` and
  ``ConsentGrant.revoked_at`` are mutated on the entity by the service and persisted by the
  request's commit, the same way ``records`` handles hospital verification.

Unbounded listings are keyset-paginated over ``(<time> DESC, id DESC)``
(app/shared/pagination.py) — never OFFSET. Bounded child collections (the categories of one
request, the decisions of one request) are returned whole, following
``RecordCategoryRepository.list_all``: both are capped by the record-category vocabulary,
so paginating them would add cursor plumbing to a fetch of at most ten rows.
"""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.consent.errors import (
    DuplicateAnchorError,
    DuplicateDecisionError,
    DuplicateGrantError,
    DuplicateRequestCategoryError,
    UnrequestedCategoryError,
)
from app.modules.consent.models import (
    AuditAnchorEntry,
    AuditLog,
    ConsentDecision,
    ConsentGrant,
    ConsentRequest,
    ConsentRequestCategory,
)
from app.shared.pagination import CursorKey


def _keyset_filter(
    time_col: InstrumentedAttribute[datetime],
    id_col: InstrumentedAttribute[UUID],
    after: CursorKey,
) -> ColumnElement[bool]:
    """WHERE clause for "strictly after ``after`` in (time DESC, id DESC) order".

    Spelled as an OR (not a row-value comparison) because SQLite lacks tuple comparison.
    ``CursorKey.created_at`` names the *time component* of the key; for ``AuditLog`` that
    component is ``occurred_at``, which is the column that table is ordered on.
    """
    return or_(
        time_col < after.created_at,
        and_(time_col == after.created_at, id_col < after.item_id),
    )


def _is_foreign_key_violation(exc: IntegrityError) -> bool:
    """Distinguish a foreign-key violation from a unique violation.

    Both arrive as ``IntegrityError``; the driver message is the only discriminator, and
    "foreign key" appears in both Postgres ("violates foreign key constraint") and SQLite
    ("FOREIGN KEY constraint failed"). Mapping per constraint rather than per table keeps a
    genuine bug from being reported as a duplicate.
    """
    return "foreign key" in str(exc.orig).lower()


class ConsentRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, request_id: UUID) -> ConsentRequest | None:
        return await self._session.get(ConsentRequest, request_id)

    async def add(self, request: ConsentRequest) -> ConsentRequest:
        """Flush a new request. No savepoint: the table carries no unique constraint, so
        an ``IntegrityError`` here would be a bug rather than a domain signal."""
        self._session.add(request)
        await self._session.flush()
        return request

    async def list_page_by_patient(
        self, patient_id: UUID, *, after: CursorKey | None, limit: int
    ) -> list[ConsentRequest]:
        """One page of the requests naming this patient, newest first (the consent inbox)."""
        return await self._page(ConsentRequest.patient_id == patient_id, after=after, limit=limit)

    async def list_page_by_requester(
        self, requester_doctor_id: UUID, *, after: CursorKey | None, limit: int
    ) -> list[ConsentRequest]:
        """One page of the requests this clinician raised, newest first."""
        return await self._page(
            ConsentRequest.requester_doctor_id == requester_doctor_id, after=after, limit=limit
        )

    async def _page(
        self, scope: ColumnElement[bool], *, after: CursorKey | None, limit: int
    ) -> list[ConsentRequest]:
        query: Select[tuple[ConsentRequest]] = (
            select(ConsentRequest)
            .where(scope)
            .order_by(ConsentRequest.created_at.desc(), ConsentRequest.id.desc())
            .limit(limit)
        )
        if after is not None:
            query = query.where(_keyset_filter(ConsentRequest.created_at, ConsentRequest.id, after))
        result = await self._session.execute(query)
        return list(result.scalars())


class ConsentRequestCategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, requested: ConsentRequestCategory) -> ConsentRequestCategory:
        """Flush one requested category; the unique (request, category) pair makes "asked
        for twice" a domain error rather than a duplicate row."""
        try:
            async with self._session.begin_nested():
                self._session.add(requested)
                await self._session.flush()
        except IntegrityError as exc:
            raise DuplicateRequestCategoryError() from exc
        return requested

    async def list_by_request(self, request_id: UUID) -> list[ConsentRequestCategory]:
        """Every category this request asked for. Bounded by the record-category
        vocabulary, so returned whole rather than paginated (see the module docstring)."""
        result = await self._session.execute(
            select(ConsentRequestCategory)
            .where(ConsentRequestCategory.request_id == request_id)
            .order_by(ConsentRequestCategory.category_id)
        )
        return list(result.scalars())


class ConsentDecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, decision_id: UUID) -> ConsentDecision | None:
        return await self._session.get(ConsentDecision, decision_id)

    async def add(self, decision: ConsentDecision) -> ConsentDecision:
        """Flush an immutable decision.

        Two constraints can refuse it and they mean different things: the composite foreign
        key rejects a category the request never asked for, and the unique pair rejects a
        second answer for a category already decided.
        """
        try:
            async with self._session.begin_nested():
                self._session.add(decision)
                await self._session.flush()
        except IntegrityError as exc:
            if _is_foreign_key_violation(exc):
                raise UnrequestedCategoryError() from exc
            raise DuplicateDecisionError() from exc
        return decision

    async def list_by_request(self, request_id: UUID) -> list[ConsentDecision]:
        """Every decision recorded against this request. Bounded by the request's own
        category set, so returned whole rather than paginated."""
        result = await self._session.execute(
            select(ConsentDecision)
            .where(ConsentDecision.request_id == request_id)
            .order_by(ConsentDecision.category_id)
        )
        return list(result.scalars())


class ConsentGrantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, grant_id: UUID) -> ConsentGrant | None:
        return await self._session.get(ConsentGrant, grant_id)

    async def add(self, grant: ConsentGrant) -> ConsentGrant:
        """Flush a new grant; the unique ``decision_id`` makes "one grant per approval" a
        constraint rather than a hope (a retried approval surfaces as a domain error)."""
        try:
            async with self._session.begin_nested():
                self._session.add(grant)
                await self._session.flush()
        except IntegrityError as exc:
            raise DuplicateGrantError() from exc
        return grant

    async def get_active(
        self, *, patient_id: UUID, grantee_doctor_id: UUID, category_id: UUID, at: datetime
    ) -> ConsentGrant | None:
        """The unrevoked, unexpired grant for this (patient, grantee, category) triple, or
        None — the ADR-013 layer-3 lookup, served in one index seek by
        ``ix_consent_grants_patient_id_grantee_doctor_id_category_id``.

        ``at`` is supplied by the caller: reading the clock is a decision, not persistence.
        Expiry and revocation are the *predicate* here, never the policy — how long a grant
        lives is the service's to set (OD-2).
        """
        result = await self._session.execute(
            select(ConsentGrant)
            .where(
                ConsentGrant.patient_id == patient_id,
                ConsentGrant.grantee_doctor_id == grantee_doctor_id,
                ConsentGrant.category_id == category_id,
                ConsentGrant.revoked_at.is_(None),
                ConsentGrant.expires_at > at,
            )
            .order_by(ConsentGrant.expires_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_active_category_ids(
        self, *, patient_id: UUID, grantee_doctor_id: UUID, at: datetime
    ) -> list[UUID]:
        """Every category this grantee may currently read for this patient — ids only.

        ``get_active`` asked the same question about one category and answered with a row;
        this asks it about all of them and answers with the set. **The predicate is
        deliberately identical** — unrevoked, and ``expires_at`` strictly greater than
        ``at`` — so a listing filtered by this method and a read authorized by
        ``get_active`` can never disagree about what is in scope (ADR-020). A grant whose
        ``expires_at`` equals ``at`` is excluded by both.

        Served by the same
        ``ix_consent_grants_patient_id_grantee_doctor_id_category_id`` index, on its two
        leading columns. Grouped rather than DISTINCT-ed in Python because several grants
        can cover one category over time (a re-approval after an expiry), and the caller
        wants the category, not its history.

        ``at`` is the caller's, for the reason ``get_active`` gives: reading the clock is a
        decision, not persistence.
        """
        result = await self._session.execute(
            select(ConsentGrant.category_id)
            .where(
                ConsentGrant.patient_id == patient_id,
                ConsentGrant.grantee_doctor_id == grantee_doctor_id,
                ConsentGrant.revoked_at.is_(None),
                ConsentGrant.expires_at > at,
            )
            .group_by(ConsentGrant.category_id)
        )
        return list(result.scalars())

    async def list_page_by_patient(
        self, patient_id: UUID, *, after: CursorKey | None, limit: int
    ) -> list[ConsentGrant]:
        """One page of every grant ever derived for this patient, newest first — revoked
        and expired rows included, because this is the patient's history, not the
        enforcement view."""
        query: Select[tuple[ConsentGrant]] = (
            select(ConsentGrant)
            .where(ConsentGrant.patient_id == patient_id)
            .order_by(ConsentGrant.created_at.desc(), ConsentGrant.id.desc())
            .limit(limit)
        )
        if after is not None:
            query = query.where(_keyset_filter(ConsentGrant.created_at, ConsentGrant.id, after))
        result = await self._session.execute(query)
        return list(result.scalars())


class AuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entry: AuditLog) -> AuditLog:
        """Append one audit row. No savepoint: the table carries no unique constraint —
        ``event_hash`` is deliberately non-unique — so an ``IntegrityError`` here would be
        a bug, not a domain signal. There is no update or delete counterpart by design."""
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def get_for_patient(self, audit_log_id: UUID, *, patient_id: UUID) -> AuditLog | None:
        """One audit event, but only if it belongs to this patient's trail.

        **The patient is part of the query, not a check after it.** A caller cannot hold the
        row of somebody else's event long enough to make a mistake with it, and a missing
        event and another patient's event are the same answer — the 403-vs-404 rule
        (docs/API_GUIDELINES.md), applied to the audit trail.
        """
        result = await self._session.execute(
            select(AuditLog).where(AuditLog.id == audit_log_id, AuditLog.patient_id == patient_id)
        )
        return result.scalar_one_or_none()

    async def list_page_by_patient(
        self, patient_id: UUID, *, after: CursorKey | None, limit: int
    ) -> list[AuditLog]:
        """One page of the patient-visible trail, most recent event first.

        Ordered on ``occurred_at`` — the application-assigned event time the hash covers —
        rather than on the row's storage timestamp, matching
        ``ix_audit_logs_patient_id_occurred_at_id``.
        """
        query: Select[tuple[AuditLog]] = (
            select(AuditLog)
            .where(AuditLog.patient_id == patient_id)
            .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
            .limit(limit)
        )
        if after is not None:
            query = query.where(_keyset_filter(AuditLog.occurred_at, AuditLog.id, after))
        result = await self._session.execute(query)
        return list(result.scalars())

    async def list_page_by_hospital(
        self, hospital_id: UUID, *, after: CursorKey | None, limit: int
    ) -> list[AuditLog]:
        """One page of a hospital's own activity, most recent event first (ADR-023).

        Filters on ``actor_hospital_id`` — the attribution captured when each event was
        written — and never on the actor's present affiliation, so a doctor who transfers
        leaves their history behind in the hospital they generated it at.

        Two classes of row are absent by construction rather than by an extra predicate:
        events by a patient actor, who has no hospital, and every event written before
        migration 0005, which is unattributed and stays that way. Same order and keyset as
        the patient listing, matching ``ix_audit_logs_actor_hospital_id_occurred_at_id``.
        """
        query: Select[tuple[AuditLog]] = (
            select(AuditLog)
            .where(AuditLog.actor_hospital_id == hospital_id)
            .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
            .limit(limit)
        )
        if after is not None:
            query = query.where(_keyset_filter(AuditLog.occurred_at, AuditLog.id, after))
        result = await self._session.execute(query)
        return list(result.scalars())


class AuditAnchorRepository:
    """Persistence for blockchain anchors of audit events (ADR-026).

    Append-only like the trail it attests to: insert and read, no update, no delete. An
    anchor that later fails verification is evidence and must survive as written.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entry: AuditAnchorEntry) -> AuditAnchorEntry:
        """Insert one anchor, in a savepoint because ``audit_log_id`` is UNIQUE.

        That constraint is the idempotency guarantee, so a collision here is a *domain*
        signal — "someone anchored this event first" — rather than a bug. Raised as
        ``DuplicateAnchorError`` for the service to resolve by reading the winner back;
        without the savepoint the failed INSERT would poison the caller's transaction and
        take the read with it.
        """
        try:
            async with self._session.begin_nested():
                self._session.add(entry)
                await self._session.flush()
        except IntegrityError as exc:
            raise DuplicateAnchorError() from exc
        return entry

    async def get_by_audit_log_id(self, audit_log_id: UUID) -> AuditAnchorEntry | None:
        result = await self._session.execute(
            select(AuditAnchorEntry).where(AuditAnchorEntry.audit_log_id == audit_log_id)
        )
        return result.scalar_one_or_none()

    async def by_audit_log_ids(
        self, audit_log_ids: Collection[UUID]
    ) -> dict[UUID, AuditAnchorEntry]:
        """Anchors for a page of events, keyed by event id.

        Batched by construction — a collection in, a mapping out — for the reason the staff
        directory is: the patient's audit listing renders 25 rows and must cost one query
        for their anchors, not 25. An event with no anchor is simply absent from the result.
        """
        if not audit_log_ids:
            return {}
        result = await self._session.execute(
            select(AuditAnchorEntry).where(AuditAnchorEntry.audit_log_id.in_(audit_log_ids))
        )
        return {entry.audit_log_id: entry for entry in result.scalars()}

    async def list_unanchored_events(self, *, limit: int) -> list[AuditLog]:
        """The oldest audit events that carry no anchor yet — the sweep's work queue.

        An anti-join rather than "everything since a watermark": anchoring can fail for one
        event and succeed for the next, so a high-water mark would strand the gap forever.
        Oldest first, so the trail anchors in the order it happened and a partial sweep
        leaves a contiguous anchored prefix rather than holes.
        """
        anchored = select(AuditAnchorEntry.audit_log_id)
        query: Select[tuple[AuditLog]] = (
            select(AuditLog)
            .where(AuditLog.id.not_in(anchored))
            .order_by(AuditLog.occurred_at.asc(), AuditLog.id.asc())
            .limit(limit)
        )
        result = await self._session.execute(query)
        return list(result.scalars())

    async def count_unanchored(self) -> int:
        anchored = select(AuditAnchorEntry.audit_log_id)
        result = await self._session.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.id.not_in(anchored))
        )
        return int(result.scalar_one())
