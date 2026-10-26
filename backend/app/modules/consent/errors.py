"""consent domain exceptions. HTTP translation happens in the boundary layer only
(docs/API_GUIDELINES.md: services never construct HTTP responses).

Only the base class and the *persistence-level* members exist so far. The latter are the
domain meanings of the database constraints migration 0004 declares — a repository
translates ``IntegrityError`` into one of them so services never see SQLAlchemy internals,
exactly as auth, patients and records do. Each is raised by exactly one constraint, so a
new constraint on these tables gets its own member rather than widening an existing one.

The rest of the taxonomy — unknown or expired request, already-decided request, no active
grant, revoked grant — belongs to the M3 service design, because each member also fixes a
status code and, for denials, must not disclose whether the underlying record exists (the
403-vs-404 rule).
"""


class ConsentError(Exception):
    """Base class for consent-module domain errors."""


class DuplicateRequestCategoryError(ConsentError):
    """The category is already on this request
    (``uq_consent_request_categories_request_id_category_id``)."""


class DuplicateDecisionError(ConsentError):
    """A decision for this (request, category) already exists — one request produces
    exactly one decision per category (``uq_consent_decisions_request_id_category_id``)."""


class UnrequestedCategoryError(ConsentError):
    """The decision names a category this request never asked for; the composite foreign
    key into ``consent_request_categories`` refused it."""


class DuplicateGrantError(ConsentError):
    """A grant already derives from this decision — an approval spawns exactly one grant
    (``uq_consent_grants_decision_id``)."""


# -- service-level errors (M3) ---------------------------------------------------------
#
# Each fixes a client-visible outcome. Where a caller has no relationship to a row, the
# error deliberately says "not found" rather than "forbidden": existence must not leak
# (docs/API_GUIDELINES.md 403-vs-404 rule).


class PatientProfileNotFoundError(ConsentError):
    """The caller holds PATIENT claims but no patient profile row exists."""


class HospitalProfileNotFoundError(ConsentError):
    """The caller holds the HOSPITAL_ADMIN role but administers no hospital, so there is no
    scope for a hospital-scoped listing (ADR-023)."""


class ClinicianProfileNotFoundError(ConsentError):
    """The caller holds DOCTOR claims but no clinician profile row exists."""


class ClinicianNotActiveError(ConsentError):
    """The clinician is not ACTIVE, so every clinical capability is refused (ADR-015)."""


class HospitalNotAcceptingRequestsError(ConsentError):
    """The clinician's hospital is not VERIFIED (e.g. SUSPENDED), so it may not initiate
    new access requests (ADR-034). Existing grants are unaffected."""


class UnknownPatientError(ConsentError):
    """No patient matches the supplied Health ID."""


class EmptyCategorySelectionError(ConsentError):
    """An access request must name at least one category — consent is per category
    (ADR-013), so an empty selection would grant nothing and mean nothing."""


class RequestNotFoundError(ConsentError):
    """No such access request *for this caller* — missing, or outside their relationship
    scope, which must be indistinguishable from missing."""


class RequestNotDecidableError(ConsentError):
    """The request is no longer open to decisions: already decided, expired, or
    cancelled. ``status`` is safe to show the client.

    Raised before a decision writes anything; the only state that may be pending when it is
    raised is the request's own lazy transition to ``EXPIRED``, which the router commits by
    returning this refusal rather than raising it (see ``consent/router.py``).
    """

    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


class DuplicatePendingRequestError(ConsentError):
    """This clinician already has an open, unexpired request to this patient that asks for
    one of these categories and has not been answered for it — a second one would only
    duplicate the patient's inbox."""


class CategoryAlreadyGrantedError(ConsentError):
    """This clinician already holds an active grant from this patient for one of these
    categories. Asking again, or approving a second grant for it, would create a duplicate
    active grant for the same (patient, clinician, category)."""


class GrantNotFoundError(ConsentError):
    """No such grant *for this caller* — missing, or belonging to another patient."""


class AccessDeniedError(ConsentError):
    """``enforce`` refused the read: no active grant covers this
    (patient, requester, category). Raised only after the denial has been audited."""


class DuplicateAnchorError(ConsentError):
    """This audit event already has an anchor (ADR-026).

    Raised by the repository when the UNIQUE on ``audit_anchors.audit_log_id`` refuses a
    second row, which is how anchoring is idempotent under concurrency rather than by a
    check-then-insert. The service catches it and returns the existing anchor: two callers
    racing to anchor one event is not an error to surface, it is the constraint working.
    """


class BatchSealConflictError(ConsentError):
    """Another sealer committed a batch first (ADR-027 decision 10).

    Raised **only** when the UNIQUE on ``audit_batches.batch_number`` or on
    ``audit_batch_members.audit_log_id`` refuses this run's rows — the two collisions a
    concurrent sealer can legitimately cause. The insert ran in a savepoint, so nothing of this
    batch was written; the caller rolls back and the next run seals whatever is still
    unbatched. Not an error to surface — the constraint working. Every other integrity
    violation is ``BatchSealIntegrityError``.
    """


class BatchSealIntegrityError(ConsentError):
    """The database refused a batch for a reason that is **not** a concurrent-sealer race.

    A CHECK, foreign-key or NOT NULL violation, a collision on a constraint no race can trip
    (the commitment, a ``(batch_id, leaf_index)`` pair, a primary key), or a violation that
    cannot be classified at all. Not retryable — the same rows would fail the same way — so
    it must reach an operator rather than a retry loop. The savepoint rolled back, so nothing
    of this batch was written.

    Carries the violation kind and, when the driver reports it, the constraint name: schema
    identifiers only, never row values, SQL, digests or connection details. The original
    database error stays attached as ``__cause__`` for logs that may hold it.
    """

    def __init__(self, *, violation: str, constraint: str | None) -> None:
        self.violation = violation
        self.constraint = constraint
        super().__init__(
            f"audit batch refused by the database: {violation} violation"
            f" ({constraint or 'constraint not identified'})"
        )


class BatchAnchoredEventError(ConsentError):
    """A v3 event was offered to the per-event anchoring workflow (ADR-027 decision 7).

    v3 events are anchored only in Merkle batches; the per-event workflow keeps serving
    historical v1/v2 rows. Carries no event content.
    """


class UnanchorableAuditEventError(ConsentError):
    """An audit event cannot be anchored per-event: its stored digest is not trustworthy.

    Raised before any adapter is called when the event's ``hash_version`` is unsupported or its
    stored digest does not recompute under that version — anchoring it would publish evidence
    for a row that is already inconsistent. ``reason`` is ``"unsupported_hash_version"`` or
    ``"digest_mismatch"``; neither the digest nor any event content is carried.
    """

    def __init__(self, *, reason: str) -> None:
        self.reason = reason
        super().__init__(f"audit event cannot be anchored per-event: {reason}")


class AuditEventNotFoundError(ConsentError):
    """No such audit event *for this caller* — missing, or belonging to another patient.

    One error for both, deliberately: the 403-vs-404 rule (docs/API_GUIDELINES.md) means a
    patient asking about somebody else's event must not learn that it exists.
    """


class AuditProofNotFoundError(ConsentError):
    """The audit event is not sealed into any Merkle batch, so no proof exists."""


class AuditBatchNotFoundError(ConsentError):
    """No sealed audit batch with the requested batch number exists."""
