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
    cancelled. ``status`` is safe to show the client."""

    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


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


class AuditEventNotFoundError(ConsentError):
    """No such audit event *for this caller* — missing, or belonging to another patient.

    One error for both, deliberately: the 403-vs-404 rule (docs/API_GUIDELINES.md) means a
    patient asking about somebody else's event must not learn that it exists.
    """
