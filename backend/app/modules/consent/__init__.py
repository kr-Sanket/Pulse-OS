"""consent module — the authorization heart of PulseOS (ADR-013 layer 3, ADR-004).

Owns the access-request → per-category decision → grant → revocation lifecycle, the
append-only audit log of every consent and record-access event, and the single
``enforce()`` choke point that every record read passes through
(docs/SYSTEM_ARCHITECTURE.md §Isolation rule 3).

Layout mirrors the other modules: ``router`` → ``service`` (domain logic) →
``repository`` (persistence only), plus ``models``, ``schemas``, ``dependencies``
(composition + RFC 7807 translation), ``errors``, and ``seed``.

Boundaries (docs/SYSTEM_ARCHITECTURE.md isolation rules):

- This module never stores files or record content. It decides *whether* a read is
  allowed and records that it happened; ``records`` owns the content and the storage port.
- Patients and clinicians are resolved through the owning modules' published service
  interfaces, never by querying their tables.
- ``RecordCategory`` is the consent granularity unit but belongs to ``records``
  (docs/DOMAIN_MODEL.md §1); consent references categories by id.

M3 scope (.claude/ROADMAP.md): request → per-category approve/reject → revoke; the
enforcement dependency wired into every record-read path; the append-only audit log; the
``AuditAnchor`` interface with a DB-backed implementation only (ADR-004 — the Polygon
anchor is M6); notification fan-out for requests.

**Status: implemented (M3, extended at M4).** The lifecycle, ``enforce``, the audit log and
the three routers are live and mounted in ``app.main``. OD-1…3 (docs/DOMAIN_MODEL.md §5)
remain open Product-Owner questions — unclaimed-patient handling, the grant-expiry default
written to ``ConsentGrant.expires_at``, and whether a grant exposes the health profile —
but none of them blocks the implemented surface.

Obligations the schema records but cannot enforce — each belongs to the service and is
listed here so it is inherited deliberately rather than discovered:

- **Normalise ``request_context`` before writing it.** ``audit_logs.request_context`` is
  unbounded ``Text`` so that an oversized client ``X-Request-Id`` can never fail the audit
  INSERT and roll back the action it records. The middleware accepts that header verbatim
  (app/core/middleware.py), so the service must cap and sanitise the value it persists; the
  database deliberately no longer does it by raising.
- **Compute ``event_hash`` over the canonical event JSON before the INSERT**, covering
  every audit column except ``created_at`` and the hash itself (ADR-004).
- **Never UPDATE or DELETE** ``consent_request_categories``, ``consent_decisions``, or
  ``audit_logs``. Those tables have no ``updated_at`` and no mutable column, but
  docs/DATABASE_DESIGN.md principle 3 also expects DB privileges to back the rule in a
  deployed environment — an ops task, not a schema one.
- **Uphold the target-column pairing** in ``audit_logs``: at most one of the three target
  references is set for any given action, and a scope-level event such as
  ``RECORDS_LISTED`` sets none (ADR-020).
"""
