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

import hashlib
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.consent.errors import (
    BatchSealConflictError,
    BatchSealIntegrityError,
    DuplicateAnchorError,
    DuplicateDecisionError,
    DuplicateGrantError,
    DuplicateRequestCategoryError,
    UnrequestedCategoryError,
)
from app.modules.consent.models import (
    AuditAnchorEntry,
    AuditBatch,
    AuditBatchMember,
    AuditLog,
    ConsentDecision,
    ConsentGrant,
    ConsentRequest,
    ConsentRequestCategory,
    ConsentRequestStatus,
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


def _is_unique_violation(exc: IntegrityError) -> bool:
    """Whether a refused write was a UNIQUE violation, read from driver metadata.

    The duplicate-translating ``add`` methods below map only this to a domain conflict; any
    other refusal (a NOT NULL, a CHECK, a foreign key a constraint does not explain) is a bug
    or corruption and propagates as itself rather than masquerading as a 409.
    """
    return classify_integrity_error(exc).kind in {"unique", "primary_key"}


def _pair_lock_key(patient_id: UUID, requester_doctor_id: UUID) -> int:
    """A stable signed 64-bit advisory-lock key for one (patient, clinician) pair."""
    digest = hashlib.sha256(
        b"pulseos:consent-pair:" + patient_id.bytes + requester_doctor_id.bytes
    ).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


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

    async def lock_pair(self, *, patient_id: UUID, requester_doctor_id: UUID) -> None:
        """Serialise consent writes for one (patient, clinician) pair until commit.

        The duplicate checks in ``ConsentService`` read before they write, and no single
        constraint can express "one open request per category" across two tables. On
        PostgreSQL, ``pg_advisory_xact_lock`` makes a concurrent creator or approver for the
        same pair wait until this transaction ends; under READ COMMITTED its next statement
        then sees what this one committed. Released automatically at transaction end. On
        SQLite (the test harness) writers are already serialised, so this is a no-op —
        the same arrangement as ``AuditBatchRepository.lock_for_sealing``.
        """
        if self._session.get_bind().dialect.name == "postgresql":
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": _pair_lock_key(patient_id, requester_doctor_id)},
            )

    async def open_category_ids(
        self, *, patient_id: UUID, requester_doctor_id: UUID, at: datetime
    ) -> set[UUID]:
        """Categories this clinician has asked this patient for on a request that is still
        open at ``at`` — PENDING, unexpired — and that the patient has not yet answered.

        A category already decided on a still-PENDING request is excluded: a rejection
        leaves the clinician free to ask again, and an approval is covered by the grant
        check instead.
        """
        result = await self._session.execute(
            select(ConsentRequestCategory.category_id)
            .join(ConsentRequest, ConsentRequest.id == ConsentRequestCategory.request_id)
            .outerjoin(
                ConsentDecision,
                and_(
                    ConsentDecision.request_id == ConsentRequestCategory.request_id,
                    ConsentDecision.category_id == ConsentRequestCategory.category_id,
                ),
            )
            .where(
                ConsentRequest.patient_id == patient_id,
                ConsentRequest.requester_doctor_id == requester_doctor_id,
                ConsentRequest.status == ConsentRequestStatus.PENDING,
                ConsentRequest.expires_at > at,
                ConsentDecision.id.is_(None),
            )
        )
        return set(result.scalars())

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
        query = (
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
            if not _is_unique_violation(exc):
                raise
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
            if not _is_unique_violation(exc):
                raise
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
            if not _is_unique_violation(exc):
                raise
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
        query = (
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
        query = (
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
        query = (
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

    async def list_unanchored_events(
        self, *, limit: int, exclude_hash_version: int | None = None
    ) -> list[AuditLog]:
        """The oldest audit events that carry no anchor yet — the sweep's work queue.

        An anti-join rather than "everything since a watermark": anchoring can fail for one
        event and succeed for the next, so a high-water mark would strand the gap forever.
        Oldest first, so the trail anchors in the order it happened and a partial sweep
        leaves a contiguous anchored prefix rather than holes. ``exclude_hash_version`` keeps
        a scheme out of the queue entirely — v3, which is batch-anchored (ADR-027).
        """
        anchored = select(AuditAnchorEntry.audit_log_id)
        query = (
            select(AuditLog)
            .where(AuditLog.id.not_in(anchored))
            .order_by(AuditLog.occurred_at.asc(), AuditLog.id.asc())
            .limit(limit)
        )
        if exclude_hash_version is not None:
            query = query.where(AuditLog.hash_version != exclude_hash_version)
        result = await self._session.execute(query)
        return list(result.scalars())

    async def count_unanchored(self, *, exclude_hash_version: int | None = None) -> int:
        anchored = select(AuditAnchorEntry.audit_log_id)
        query = select(func.count()).select_from(AuditLog).where(AuditLog.id.not_in(anchored))
        if exclude_hash_version is not None:
            query = query.where(AuditLog.hash_version != exclude_hash_version)
        result = await self._session.execute(query)
        return int(result.scalar_one())


#: Key of the transaction-scoped PostgreSQL advisory lock that serialises batch sealers. An
#: arbitrary fixed 63-bit value; it only has to be the same in every sealer.
_SEALING_LOCK_KEY = 0x5055_4C53_4542_4154  # "PULSEBAT"

#: Constraints whose collision *is* a concurrent-sealer race (ADR-027 decision 10): two sealers
#: claiming the same next number, or batching the same event. Nothing else is, by itself.
SEALING_RACE_CONSTRAINTS: Final = frozenset(
    {"uq_audit_batches_batch_number", "uq_audit_batch_members_audit_log_id"}
)

#: A collision here is a race **only conditionally**. When two sealers seal the identical batch
#: (same number, same events, same root) both ``batch_number`` and ``commitment`` collide, and
#: which UNIQUE index reports first is backend-dependent — SQLite reports this one. Because the
#: commitment binds the batch number, the collision is a race exactly when a batch with this
#: run's number already exists; otherwise a stored batch carries a commitment that does not match
#: its own number, which is tampering, not contention.
COMMITMENT_CONSTRAINT: Final = "uq_audit_batches_commitment"

#: PostgreSQL integrity SQLSTATEs (class 23) this module distinguishes.
_POSTGRES_SQLSTATE_KINDS: Final = {
    "23505": "unique",
    "23514": "check",
    "23503": "foreign_key",
    "23502": "not_null",
}

#: SQLite's extended result names for constraint failures (``sqlite3.Error.sqlite_errorname``).
_SQLITE_ERRORNAME_KINDS: Final = {
    "SQLITE_CONSTRAINT_UNIQUE": "unique",
    "SQLITE_CONSTRAINT_PRIMARYKEY": "primary_key",
    "SQLITE_CONSTRAINT_CHECK": "check",
    "SQLITE_CONSTRAINT_FOREIGNKEY": "foreign_key",
    "SQLITE_CONSTRAINT_NOTNULL": "not_null",
}

#: SQLite names no constraint for a UNIQUE failure — only ``table.column`` lists, in the fixed
#: form ``UNIQUE constraint failed: <columns>``. Exact strings for this module's batch UNIQUE
#: constraints; any other text identifies nothing, which is the fail-closed answer.
_SQLITE_UNIQUE_MESSAGES: Final = {
    "UNIQUE constraint failed: audit_batches.batch_number": "uq_audit_batches_batch_number",
    "UNIQUE constraint failed: audit_batches.commitment": "uq_audit_batches_commitment",
    "UNIQUE constraint failed: audit_batch_members.audit_log_id": (
        "uq_audit_batch_members_audit_log_id"
    ),
    "UNIQUE constraint failed: audit_batch_members.batch_id, audit_batch_members.leaf_index": (
        "uq_audit_batch_members_batch_id_leaf_index"
    ),
}


@dataclass(frozen=True, slots=True)
class IntegrityViolation:
    """What kind of constraint refused a write, and which one when the driver says so.

    ``kind`` is ``unique``, ``primary_key``, ``check``, ``foreign_key``, ``not_null`` or
    ``unknown``; ``constraint`` is a schema identifier or ``None`` when it cannot be
    established. Both are safe to log: no row values, SQL or connection details.
    """

    kind: str
    constraint: str | None

    @property
    def is_sealing_race(self) -> bool:
        return self.kind == "unique" and self.constraint in SEALING_RACE_CONSTRAINTS


def classify_integrity_error(exc: IntegrityError) -> IntegrityViolation:
    """Classify a refused write from structured driver metadata, failing closed.

    * **PostgreSQL (asyncpg):** SQLAlchemy's adapter sets ``sqlstate`` on ``exc.orig`` and
      chains the asyncpg error, whose ``constraint_name`` names the constraint.
    * **SQLite (the test harness):** ``sqlite_errorname`` gives the kind. A UNIQUE failure
      carries no constraint name, so it is identified only by an exact match of SQLite's fixed
      message against the batch constraints above — never by partial parsing.

    Anything else — another driver, a missing attribute, an unlisted SQLSTATE or message —
    is ``unknown`` or has no constraint, and so is never mistaken for a sealing race.
    """
    orig = exc.orig
    sqlstate = getattr(orig, "sqlstate", None)
    if isinstance(sqlstate, str):
        name = getattr(getattr(orig, "__cause__", None), "constraint_name", None)
        return IntegrityViolation(
            kind=_POSTGRES_SQLSTATE_KINDS.get(sqlstate, "unknown"),
            constraint=name if isinstance(name, str) else None,
        )
    errorname = getattr(orig, "sqlite_errorname", None)
    if isinstance(errorname, str):
        kind = _SQLITE_ERRORNAME_KINDS.get(errorname, "unknown")
        constraint = _SQLITE_UNIQUE_MESSAGES.get(str(orig)) if kind == "unique" else None
        return IntegrityViolation(kind=kind, constraint=constraint)
    return IntegrityViolation(kind="unknown", constraint=None)


class AuditBatchRepository:
    """Persistence for sealed Merkle batches and their membership (ADR-027).

    Append-only: insert and read, never update or delete. Like every repository here it
    flushes and never commits; sealing's atomicity comes from the savepoint in
    ``add_sealed_batch`` plus the caller's transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_for_sealing(self) -> None:
        """Serialise sealers for the rest of this transaction.

        On PostgreSQL, ``pg_advisory_xact_lock`` makes a second sealer wait until the first
        commits or rolls back; its following statements then see the committed batch, so it
        selects only what is still unbatched instead of colliding. Released automatically at
        transaction end. On SQLite (the test harness) writers are already serialised by the
        database lock, so this is a no-op. Either way the UNIQUE constraints remain the
        backstop — the lock avoids wasted work, it is not what makes sealing correct.
        """
        if self._session.get_bind().dialect.name == "postgresql":
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SEALING_LOCK_KEY}
            )

    async def list_unbatched_events(self, *, hash_version: int, limit: int) -> list[AuditLog]:
        """The oldest events of ``hash_version`` not yet in any batch, canonical order.

        Canonical order is ``(occurred_at, id)``, the order ``V3Batch`` assigns positions
        in, so the selected prefix is the one the batch would choose anyway.
        """
        batched = select(AuditBatchMember.audit_log_id)
        query = (
            select(AuditLog)
            .where(AuditLog.hash_version == hash_version, AuditLog.id.not_in(batched))
            .order_by(AuditLog.occurred_at.asc(), AuditLog.id.asc())
            .limit(limit)
        )
        result = await self._session.execute(query)
        return list(result.scalars())

    async def all_unbatched_events(self, *, hash_version: int | None = None) -> list[AuditLog]:
        """Every unbatched event, canonical order — reconciliation's input.

        ``hash_version=None`` returns unbatched events of **every** version, including ones
        no scheme defines: reconciliation recomputes each under its own label, which is how a
        v3 event relabelled to v2 before sealing is found (ADR-027 decision 13).
        """
        batched = select(AuditBatchMember.audit_log_id)
        query = (
            select(AuditLog)
            .where(AuditLog.id.not_in(batched))
            .order_by(AuditLog.occurred_at.asc(), AuditLog.id.asc())
        )
        if hash_version is not None:
            query = query.where(AuditLog.hash_version == hash_version)
        result = await self._session.execute(query)
        return list(result.scalars())

    async def next_batch_number(self) -> int:
        """One more than the highest batch number, or 1. Contention is settled by UNIQUE."""
        result = await self._session.execute(select(func.max(AuditBatch.batch_number)))
        highest = result.scalar_one_or_none()
        return 1 if highest is None else int(highest) + 1

    async def add_sealed_batch(
        self, batch: AuditBatch, members: list[AuditBatchMember]
    ) -> AuditBatch:
        """Insert a batch and all its members in one savepoint — all of it, or none.

        On any integrity violation the savepoint rolls back every row of this batch, so no
        partial membership can survive. The violation is then classified:

        * a UNIQUE collision on ``batch_number`` or ``audit_log_id`` — another sealer won — is
          ``BatchSealConflictError``: roll back and let the next run retry. So is a collision
          on the commitment when a batch with this run's number now exists: the winner sealed
          the identical batch (see ``COMMITMENT_CONSTRAINT``);
        * anything else (CHECK, foreign key, NOT NULL, any other UNIQUE, a commitment collision
          with no such batch, or unclassifiable) is ``BatchSealIntegrityError``: not
          retryable, it needs an operator.
        """
        batch_number = batch.batch_number  # read before the savepoint can expunge ``batch``
        try:
            async with self._session.begin_nested():
                self._session.add(batch)
                await self._session.flush()
                self._session.add_all(members)
                await self._session.flush()
        except IntegrityError as exc:
            violation = classify_integrity_error(exc)
            identical_batch_won = (
                violation.kind == "unique"
                and violation.constraint == COMMITMENT_CONSTRAINT
                and await self._batch_number_taken(batch_number)
            )
            if violation.is_sealing_race or identical_batch_won:
                raise BatchSealConflictError() from exc
            raise BatchSealIntegrityError(
                violation=violation.kind, constraint=violation.constraint
            ) from exc
        return batch

    async def _batch_number_taken(self, batch_number: int) -> bool:
        """Whether a batch with ``batch_number`` exists. Runs after the savepoint rolled back,
        in the same transaction; on PostgreSQL a UNIQUE violation is only raised once the
        conflicting row has committed, so a read-committed SELECT sees it."""
        result = await self._session.execute(
            select(AuditBatch.id).where(AuditBatch.batch_number == batch_number).limit(1)
        )
        return result.first() is not None

    async def list_batches(self) -> list[AuditBatch]:
        result = await self._session.execute(
            select(AuditBatch).order_by(AuditBatch.batch_number.asc())
        )
        return list(result.scalars())

    async def get_batch_by_id(self, batch_id: UUID) -> AuditBatch | None:
        """Fetch one sealed batch by its UUID primary key."""
        return await self._session.get(AuditBatch, batch_id)

    async def get_batch_by_number(self, batch_number: int) -> AuditBatch | None:
        """Fetch one sealed batch by its contiguous sequential number."""
        result = await self._session.execute(
            select(AuditBatch).where(AuditBatch.batch_number == batch_number)
        )
        return result.scalar_one_or_none()

    async def get_member_by_audit_log_id(self, audit_log_id: UUID) -> AuditBatchMember | None:
        """Fetch the membership record linking an audit event to its batch."""
        result = await self._session.execute(
            select(AuditBatchMember).where(AuditBatchMember.audit_log_id == audit_log_id)
        )
        return result.scalar_one_or_none()

    async def list_members_for_batch(self, batch_id: UUID) -> list[AuditBatchMember]:
        """Fetch all members of a batch ordered by leaf position (0 .. n-1)."""
        result = await self._session.execute(
            select(AuditBatchMember)
            .where(AuditBatchMember.batch_id == batch_id)
            .order_by(AuditBatchMember.leaf_index.asc())
        )
        return list(result.scalars())

    async def get_event_by_id(self, audit_log_id: UUID) -> AuditLog | None:
        """Fetch an audit log entry by UUID primary key."""
        return await self._session.get(AuditLog, audit_log_id)

    async def list_members_with_events(
        self,
    ) -> list[tuple[AuditBatchMember, AuditLog | None]]:
        """Every membership row with its audit event, by batch then position.

        An outer join: a member whose event row has gone missing must come back with
        ``None`` rather than vanish, because that absence is exactly what reconciliation is
        looking for.
        """
        result = await self._session.execute(
            select(AuditBatchMember, AuditLog)
            .outerjoin(AuditLog, AuditLog.id == AuditBatchMember.audit_log_id)
            .order_by(AuditBatchMember.batch_id, AuditBatchMember.leaf_index)
        )
        return [(member, event) for member, event in result.tuples()]
