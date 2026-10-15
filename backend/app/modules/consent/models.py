"""consent-owned tables: the access-request lifecycle, per-category decisions, the active
grants enforcement reads, and the append-only audit log (docs/DOMAIN_MODEL.md §1).

Conventions are identical to app/modules/records/models.py: UUID primary keys, enum columns
as non-native VARCHAR with the *values* persisted (so extending a vocabulary never requires
a constraint migration), no ``relationship()`` anywhere, and cross-module links as plain
UUID foreign keys — referential integrity only, never an ORM graph crossing a module
boundary (docs/SYSTEM_ARCHITECTURE.md rule 1; docs/DOMAIN_MODEL.md §2 cardinal rule 4).

Three invariants shape the tables below.

**History is immutable.** ``ConsentRequestCategory``, ``ConsentDecision`` and ``AuditLog``
are written once and never updated (docs/DATABASE_DESIGN.md principle 3, ADR-004), so they
carry ``created_at`` alone — no ``updated_at``, and no ``onupdate`` hook that would
instrument a mutation the design forbids. ``ConsentRequest`` and ``ConsentGrant`` are
genuinely mutable state (a status transition; a revocation) and keep the shared
``TimestampMixin``. Which mixin a table uses is therefore a statement about whether its
rows may change.

**Enforcement never walks history.** ADR-013 layer 3 and docs/DATABASE_DESIGN.md §Modeling
Rules require revocation to be O(1) to enforce, so ``ConsentGrant`` carries the
(patient, grantee, category) triple directly and is indexed on it. That triple is
reachable by joining decision → request, and is materialised here deliberately: the
enforcement check must be a single index lookup on the hot path of every non-owner record
read, not a three-table join. ``decision_id`` keeps the provenance link so a grant can
always be traced to the approval that created it and reconciled against it.

**A decision can only answer a question that was asked.** ``ConsentRequestCategory`` is the
requested set; ``ConsentDecision`` references it by the composite key
(request_id, category_id) rather than by two independent foreign keys, so a decision on a
category the request never named is rejected by the database rather than by a service
check.

``AuditAnchorEntry`` is the anchor receipt of docs/DOMAIN_MODEL.md §2 and ADR-004, and it is
a **separate table precisely because ``AuditLog`` is append-only**: a receipt arrives after
the event and cannot be an UPDATE to a row that is never updated. It holds a digest and a
transaction reference — never a copy of the event (ADR-026).
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.auth.domain import Role

#: ``created_at`` for append-only tables — the shared ``TimestampMixin`` cannot be used
#: because it also brings ``updated_at`` with an ``onupdate`` hook. The plain (non-variant)
#: timestamp type is safe here only because no append-only table below is keyset-paginated
#: on this column; the SQLite microsecond truncation in app/core/db.py exists for cursor
#: equality, and ``AuditLog`` paginates on the application-assigned ``occurred_at`` instead.
#: A paginated listing added over any of these tables must revisit this.
_APPEND_ONLY_CREATED_AT = DateTime(timezone=True)


def _enum_values(enum_cls: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_cls]


class ConsentRequestStatus(StrEnum):
    """Lifecycle of a clinician's petition (docs/DOMAIN_MODEL.md §1).

    ``DECIDED`` means the patient answered every requested category — approving some and
    rejecting others is still a decided request. ``EXPIRED`` is reached by the sweep when
    ``expires_at`` passes with the request still ``PENDING``; ``CANCELLED`` is the
    requester withdrawing.
    """

    PENDING = "PENDING"
    DECIDED = "DECIDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ConsentDecisionStatus(StrEnum):
    """The patient's answer for one category. Two members only, by design: a decision is
    an immutable historical fact, so there is no pending state to occupy and no revoked
    state to transition into — revocation is recorded on the derived ``ConsentGrant`` plus
    a new audit event (docs/DOMAIN_MODEL.md §1).
    """

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AuditAction(StrEnum):
    """The audit action vocabulary of docs/DOMAIN_MODEL.md §1, verbatim.

    ``ACCESS_DENIED`` extends that list. The M3 gate requires that "attempted unauthorized
    reads are denied AND logged" (.claude/ROADMAP.md) and ``RECORD_VIEWED`` records only
    successes, so a refused read had no truthful action to write. Adding it costs nothing:
    members are values in a VARCHAR(32) column, so the vocabulary extends without a
    migration.

    ``RECORDS_LISTED`` extends it again, for the same reason and by the same precedent
    (ADR-020). A clinician asking which of a patient's records they may read is a real
    access event — SYSTEM_ARCHITECTURE rule 3 covers "metadata-beyond-existence" — and no
    existing member states it truthfully: ``RECORD_VIEWED`` means one document was read and
    is paired with a record id, so reusing it would either invent views that never happened
    or leave that pairing unfilled. It is the one member whose event has **no** target at
    all: its subject is a scope, which ``patient_id`` already carries. See the target-column
    note on ``AuditLog``.

    ``RECORDS_SEARCHED`` extends it a third time (ADR-020, amendment of 2026-10-15): a
    clinician's AI record search (``GET /ai/patients/{id}/search``) returns record *text*
    from the granted scope, which ``RECORDS_LISTED`` — a chooser of ids — understated. Same
    shape as a listing: one scope-level row, no target. Rows written before it existed keep
    ``RECORDS_LISTED``; nothing is rewritten.

    ``EMERGENCY_ACCESS`` is deliberately absent: break-glass is Phase 2 and needs its own
    ADR (.claude/TODO.md parking lot), and an unused member here would imply a capability
    that docs/SECURITY.md's no-break-glass invariant denies.
    """

    RECORD_UPLOADED = "RECORD_UPLOADED"
    ACCESS_REQUESTED = "ACCESS_REQUESTED"
    CONSENT_APPROVED = "CONSENT_APPROVED"
    CONSENT_REJECTED = "CONSENT_REJECTED"
    CONSENT_REVOKED = "CONSENT_REVOKED"
    RECORD_VIEWED = "RECORD_VIEWED"
    RECORD_DOWNLOADED = "RECORD_DOWNLOADED"
    SUMMARY_GENERATED = "SUMMARY_GENERATED"
    ACCESS_DENIED = "ACCESS_DENIED"
    RECORDS_LISTED = "RECORDS_LISTED"
    RECORDS_SEARCHED = "RECORDS_SEARCHED"


class ConsentRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A clinician's petition to read a patient's records (docs/DOMAIN_MODEL.md §1).

    Mutable by design — ``status`` transitions PENDING → DECIDED | EXPIRED | CANCELLED —
    which is why this table keeps ``TimestampMixin`` while the append-only tables do not.

    The requester's hospital is captured here rather than read back through the doctor,
    because affiliation can change and the audit trail must show where the request came
    from *at the time it was made*.

    ``expires_at`` is stored per row and always set by the service; the 7-day default is
    policy and lives in configuration, not in the schema — the same reason the record
    upload cap is a setting rather than a constraint.

    The requested categories live in ``ConsentRequestCategory``, so a still-``PENDING``
    request records both that access was asked for and what was asked for.
    """

    __tablename__ = "consent_requests"

    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("patients.id"), nullable=False)
    requester_doctor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("doctors.id"), nullable=False
    )
    # Provenance, not a lookup: the hospital the requester acted for at request time.
    requester_hospital_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("hospitals.id"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ConsentRequestStatus] = mapped_column(
        Enum(
            ConsentRequestStatus,
            name="consent_request_status",
            native_enum=False,
            length=20,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=ConsentRequestStatus.PENDING,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # Both listings — the patient's inbox and the doctor's sent requests — are
        # keyset-paginated over (created_at DESC, id DESC) within one scope. A composite
        # index serves the predicate AND the order, so a page is an index range scan with
        # no sort; Postgres reads the same index backwards for the DESC walk.
        Index("ix_consent_requests_patient_id_created_at_id", "patient_id", "created_at", "id"),
        Index(
            "ix_consent_requests_requester_doctor_id_created_at_id",
            "requester_doctor_id",
            "created_at",
            "id",
        ),
        # requester_hospital_id carries no query path in M3 and hospitals are never
        # deleted (docs/DATABASE_DESIGN.md principle 5), so it is intentionally unindexed.
    )


class ConsentRequestCategory(UUIDPrimaryKeyMixin, Base):
    """One category a request asked for — the normalised requested set
    (docs/SYSTEM_ARCHITECTURE.md §Consent Flow step 2: "categories: e.g. CBC, MRI").

    Append-only: the asked-for set is fixed when the request is created. Widening a
    request is a new request, not an edit, so this table carries ``created_at`` only.

    The unique constraint is load-bearing beyond de-duplication: it is the parent key that
    ``ConsentDecision`` references, which is what makes "a decision may only answer a
    category that was requested" a database guarantee. Its index also serves every
    "categories of this request" read, so ``request_id`` needs no separate index.

    The category itself is a ``records``-owned row (docs/DOMAIN_MODEL.md §1 — the consent
    granularity unit is a seeded table, not an enum); consent references it by UUID and
    never queries that table directly.
    """

    __tablename__ = "consent_request_categories"

    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("consent_requests.id"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("record_categories.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        _APPEND_ONLY_CREATED_AT, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "request_id", "category_id", name="uq_consent_request_categories_request_id_category_id"
        ),
    )


class ConsentDecision(UUIDPrimaryKeyMixin, Base):
    """The immutable record of one per-category answer (docs/DOMAIN_MODEL.md §1).

    Written once, never updated, never deleted (docs/DATABASE_DESIGN.md principle 3), so
    ``created_at`` from this table *is* the decision instant — there is no separate
    ``decided_at`` that could disagree with it, and no ``updated_at`` at all.

    (request_id, category_id) is a composite foreign key into ``ConsentRequestCategory``
    rather than two independent references, so the database rejects a decision on a
    category the request never asked for. Integrity for each column individually still
    holds transitively through that table's own foreign keys, which is why no separate FK
    to ``consent_requests`` or ``record_categories`` is declared here.

    The unique constraint encodes the cardinal rule that one request produces exactly one
    decision per category. It holds precisely because revocation is a new event rather
    than a second decision on the same pair; if that ever changes, this constraint is the
    thing that will fail first, which is the intent. It also provides the index the
    composite foreign key needs.
    """

    __tablename__ = "consent_decisions"

    request_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)
    status: Mapped[ConsentDecisionStatus] = mapped_column(
        Enum(
            ConsentDecisionStatus,
            name="consent_decision_status",
            native_enum=False,
            length=20,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        _APPEND_ONLY_CREATED_AT, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "request_id", "category_id", name="uq_consent_decisions_request_id_category_id"
        ),
        ForeignKeyConstraint(
            ["request_id", "category_id"],
            ["consent_request_categories.request_id", "consent_request_categories.category_id"],
            name="fk_consent_decisions_consent_request_categories_request_id",
        ),
    )


class ConsentGrant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The *active* permission an approval spawns — what enforcement reads
    (docs/DOMAIN_MODEL.md §1, ADR-013 layer 3).

    Mutable by design: ``revoked_at`` is set in place, which is what makes revocation
    take effect immediately for every subsequent read. That single mutable column is the
    reason this table keeps ``TimestampMixin`` while decisions and audit rows do not.

    The grantee is the **individual doctor**, never the hospital (ADR-013: tightest
    sensible scope; hospital-wide grants are future scope), and the scope is one category.

    ``created_at`` is the moment the grant came into force, so no separate ``granted_at``
    column exists. ``expires_at`` is always set by the service; its default is policy
    (OD-2, docs/DOMAIN_MODEL.md §5), not schema.

    Deliberately **not** unique on (patient, grantee, category): a grant that expires or is
    revoked stays as history, and a later request may legitimately re-grant the same
    triple. Enforcement therefore reads "an unrevoked, unexpired row exists", which the
    composite index answers in one lookup. Uniqueness is enforced where it is actually
    true — one grant per approval, via ``decision_id``.
    """

    __tablename__ = "consent_grants"

    # Provenance: the approval this grant derives from. Unique, because an approval spawns
    # exactly one grant — the guard against double-spawning on a retry.
    decision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("consent_decisions.id"), unique=True, nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("patients.id"), nullable=False)
    grantee_doctor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("doctors.id"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("record_categories.id"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # The enforcement lookup, on the hot path of every non-owner record read:
        # WHERE patient_id = ? AND grantee_doctor_id = ? AND category_id = ?
        # then filter revoked_at / expires_at over the few rows that match.
        Index(
            "ix_consent_grants_patient_id_grantee_doctor_id_category_id",
            "patient_id",
            "grantee_doctor_id",
            "category_id",
        ),
    )


class AuditLog(UUIDPrimaryKeyMixin, Base):
    """Append-only, patient-visible record of every consent and access event
    (docs/DOMAIN_MODEL.md §1; FHIR AuditEvent per ADR-006).

    Written in the same transaction as the action it describes (.claude/CHECKLIST.md), so
    an action that commits without its audit row is impossible by construction. Append-only
    in the strict sense: no ``updated_at``, no mutable column, nothing to UPDATE.

    **Two timestamps, deliberately.** ``occurred_at`` is assigned by the application when
    the event is constructed and is part of the hashed payload; ``created_at`` is assigned
    by the database when the row lands and is not hashed. This is what makes ``event_hash``
    computable at all — see below — and it turns clock divergence into a signal: a tampered
    ``occurred_at`` breaks the hash, while a tampered ``created_at`` diverges from an
    ``occurred_at`` that still verifies.

    **``event_hash`` covers every column except ``created_at`` and itself** — id,
    actor_user_id, actor_role, action, patient_id, the three target columns,
    request_context and occurred_at. All of them are known before the INSERT (the primary
    key is client-generated per docs/DATABASE_DESIGN.md principle 6), so the canonical JSON
    can be serialised and hashed in the same statement that writes the row. Hashing
    ``created_at`` would be impossible without either a second write — which append-only
    forbids — or excluding the timestamp entirely, which would leave the moment of the
    event untamper-evident and weaken exactly the property ADR-004 exists to provide.
    The digest is 64 lowercase hex characters with no ``0x`` prefix. **The algorithm is a
    function of ``hash_version``** (app/modules/consent/service.py): SHA-256 for v1 and v2,
    Ethereum Keccak-256 — what a Solidity contract verifies (ADR-004, ADR-019) — for v3,
    which new rows are written under. Rows written earlier keep their SHA-256 digests and
    verify under them, because this table is append-only and a stored digest is never
    recomputed. The digest is what ``AuditAnchor`` publishes (ADR-004: hashes only, never
    identifiers or PHI) — locally via ``LocalChainAuditAnchor``, on-chain at M6. It is not
    unique: two genuinely distinct events must never be blocked by a collision in a column
    whose whole purpose is tamper evidence.

    The actor's role is stored alongside the actor, not looked up: roles can change, and
    the trail must show the authority the actor held at the time. ``Role`` is auth's
    published identity vocabulary (ADR-013) — a domain type, not a foreign table, so
    importing it crosses no isolation boundary.

    **At most one** of the three target columns is set for any given action (a record for
    ``RECORD_VIEWED``, a category for a consent decision, a request for
    ``ACCESS_REQUESTED``); all three are nullable because the vocabulary spans different
    subjects, and the pairing rule is the service's to uphold — no column combination in
    this table can express it.

    The rule read "exactly one" until ADR-020. ``RECORDS_LISTED`` is an event about a
    **scope** rather than an object: one clinician listing spans every category they hold a
    grant for and every record inside them, so no single target column could be filled
    truthfully, and filling one per row would multiply a single action into a page-sized
    burst. Such an event sets none of the three, and ``patient_id`` — never nullable — is
    what identifies its subject. The invariant that still holds without exception is the
    one that matters: **never more than one**.

    ``request_context`` is the ``X-Request-Id`` correlation key (docs/API_GUIDELINES.md).
    It is unbounded ``Text`` rather than a sized column on purpose: that header is
    client-supplied and unvalidated (app/core/middleware.py takes it verbatim), and a
    length ceiling here would turn an oversized header into a failed INSERT that rolls back
    the audited action itself. An audit write must never be the reason a consent decision
    fails. The companion service-side obligation — normalise and cap what is written — is
    noted in the module scaffold and does not belong in the schema.
    """

    __tablename__ = "audit_logs"

    actor_user_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("users.id"), nullable=False)
    actor_role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            name="audit_actor_role",
            native_enum=False,
            length=20,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    action: Mapped[AuditAction] = mapped_column(
        Enum(
            AuditAction,
            name="audit_action",
            native_enum=False,
            length=32,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    # The subject of the event: the patient whose data it concerns, always present —
    # this is the column that makes the log patient-visible.
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("patients.id"), nullable=False)
    target_record_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("medical_records.id")
    )
    target_category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("record_categories.id")
    )
    target_request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("consent_requests.id")
    )
    # Historical hospital attribution (ADR-023), captured when the event is written and
    # never reconstructed afterwards. Nullable because a patient actor has no hospital —
    # and because legacy rows predate the column and must stay unattributed rather than be
    # backfilled from an affiliation that may since have changed.
    actor_hospital_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), ForeignKey("hospitals.id"))
    request_context: Mapped[str | None] = mapped_column(Text())
    # Application-assigned event time: hashed, and the column the patient's log is ordered
    # and keyset-paginated on. Being application-assigned, it needs no SQLite microsecond
    # variant — the mismatch that fix guards against only arises for server-generated
    # timestamps compared against application-bound cursor values.
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Which hashing scheme produced `event_hash` — canonicalization and algorithm together
    # (ADR-023). v1 is revision 0004's ten-key payload under SHA-256; v2 adds
    # `actor_hospital_id`; v3 is v2's payload under Keccak-256 (ADR-019). Deliberately not
    # part of the hashed payload: a mis-selected scheme is self-detecting, because
    # recomputing under the wrong one changes the key set and so changes the digest.
    hash_version: Mapped[int] = mapped_column(
        SmallInteger(), server_default=text("1"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        _APPEND_ONLY_CREATED_AT, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # The patient's audit view: one scope, keyset order over the event time.
        Index("ix_audit_logs_patient_id_occurred_at_id", "patient_id", "occurred_at", "id"),
        # The hospital's audit view (ADR-023), the same shape one scope over. Rows with no
        # hospital — every patient-actor event, and every row written before 0005 — are
        # simply absent from it.
        Index(
            "ix_audit_logs_actor_hospital_id_occurred_at_id",
            "actor_hospital_id",
            "occurred_at",
            "id",
        ),
        # The three target FKs and actor_user_id are unindexed on purpose: M3 defines no
        # query that leads with them, and none of their parents is ever deleted
        # (docs/DATABASE_DESIGN.md principle 5). Revisit when a per-record or per-actor
        # trail view is actually built.
    )


class AuditAnchorEntry(UUIDPrimaryKeyMixin, Base):
    """The blockchain anchor of one audit event — metadata and proof, never content
    (ADR-004, ADR-026; docs/BLOCKCHAIN_ARCHITECTURE.md).

    **This table does not duplicate the event.** It carries no actor, no patient, no action,
    no target and no request context: those live in ``audit_logs``, which stays the
    authoritative store and the only read path. What is here is the digest that was
    published, where it was published, and how to find it again — the minimum needed to ask
    "did this exact event exist when we said it did".

    **One anchor per event, enforced by the schema.** ``audit_log_id`` is UNIQUE, so
    idempotency is a database guarantee rather than a check-then-insert race: a second
    anchoring attempt for the same event cannot create a second row even under concurrency,
    and the service reads the winner back instead of failing.

    **``digest`` is stored rather than re-read from the event, and that redundancy is the
    entire point.** Verification compares three independently stored things — the digest
    recomputed from the ``audit_logs`` row, the ``event_hash`` on that row, and the value
    recorded here as anchored. Tampering that updates the row *and* recomputes its hash
    still diverges from this copy. ``hash_version`` travels with it because a digest means
    nothing without the scheme that produced it (ADR-023), and because ADR-019's keccak
    transition must be able to tell anchored-under-SHA-256 rows from anchored-under-keccak
    ones rather than silently comparing across algorithms.

    Append-only, like the trail it attests to: no ``updated_at``, nothing to UPDATE. An
    anchor that turns out to be wrong is evidence, not a row to correct.
    """

    __tablename__ = "audit_anchors"

    audit_log_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("audit_logs.id"), unique=True, nullable=False
    )
    #: The event digest exactly as published — a copy of ``audit_logs.event_hash`` at
    #: anchoring time, kept so a later divergence between the two is detectable.
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The hashing scheme that produced ``digest`` (app/modules/consent/service.py).
    hash_version: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    #: Which chain/adapter holds the anchor — ``local-dev`` today, a real network at M6.
    #: Stored so a development anchor can never be mistaken for a chain one.
    network: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Transaction-like identifier returned by the adapter (``0x`` + 64 hex so far). Sized
    #: for that and a little more; it is an opaque handle, never parsed.
    reference: Mapped[str] = mapped_column(String(80), nullable=False)
    #: When the adapter reported the anchor. Not the event's own ``occurred_at``, and not
    #: hashed into anything — an anchor's job is to attest to a digest, not to re-time it.
    anchored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        _APPEND_ONLY_CREATED_AT, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # The sweep's query: "audit events with no anchor yet", an anti-join that leads
        # with this column. UNIQUE already indexes it, so this is documentation of the
        # access path rather than a second index.
        Index("ix_audit_anchors_anchored_at", "anchored_at"),
    )


class AuditBatch(UUIDPrimaryKeyMixin, Base):
    """One sealed Merkle batch of verified v3 audit events (ADR-027).

    **Evidence, written once.** Every column is fixed at sealing: there is no status, no
    ``updated_at``, nothing to UPDATE. Whether the batch still checks out is computed on
    demand by reconciliation, never stored here (ADR-027 decision 9). A receipt from a chain,
    when submission lands, is a separate append-only row.

    ``batch_number`` is UNIQUE and contiguous from 1, assigned at sealing; it is one of the
    four values bound into ``commitment``, so a deleted or renumbered batch is detectable.
    ``commitment`` is the only value ever published (ADR-027 decision 5) and is computed
    from ``(protocol_version, batch_number, leaf_count, root)``; reconciliation recomputes it.
    ``first_occurred_at``/``last_occurred_at`` record the covered range for late-arrival
    detection. No event content lives here — membership rows carry ids and digests only.
    """

    __tablename__ = "audit_batches"

    batch_number: Mapped[int] = mapped_column(BigInteger(), unique=True, nullable=False)
    #: Merkle protocol version (``merkle.MERKLE_PROTOCOL_VERSION``); 1 is ADR-027's.
    protocol_version: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    #: Hash scheme of every member digest — always v3; v1/v2 events are never batched.
    hash_version: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    leaf_count: Mapped[int] = mapped_column(Integer(), nullable=False)
    root: Mapped[str] = mapped_column(String(64), nullable=False)
    commitment: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    first_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        _APPEND_ONLY_CREATED_AT, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("batch_number >= 1", name="batch_number_positive"),
        CheckConstraint("leaf_count >= 1", name="leaf_count_positive"),
        CheckConstraint("hash_version = 3", name="hash_version_v3"),
    )


class AuditBatchMember(UUIDPrimaryKeyMixin, Base):
    """One audit event's place in a sealed batch (ADR-027 decision 8). Written once.

    **UNIQUE ``audit_log_id``: one batch per event, ever** — the constraint that makes a
    concurrent or repeated sealing run unable to batch an event twice. ``leaf_index`` is the
    authoritative position, UNIQUE within a batch and contiguous from 0; a proof's own
    index/count are claims checked against it (``verify_proof``'s trusted values).
    ``digest`` is the event's v3 digest as sealed, kept beside the event's own copy so a
    later divergence between them is detectable — the same redundancy ``audit_anchors``
    relies on.
    """

    __tablename__ = "audit_batch_members"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("audit_batches.id"), nullable=False
    )
    audit_log_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("audit_logs.id"), unique=True, nullable=False
    )
    leaf_index: Mapped[int] = mapped_column(Integer(), nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        _APPEND_ONLY_CREATED_AT, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "batch_id", "leaf_index", name="uq_audit_batch_members_batch_id_leaf_index"
        ),
        CheckConstraint("leaf_index >= 0", name="leaf_index_non_negative"),
    )
