# ROADMAP.md — Milestones & Phase Gates

> Revised from the original 7-month plan (see PROJECT_OVERVIEW.md for the original).
> Two structural changes, both approved in the architecture review:
> 1. A **walking skeleton** ships end of Month 2 — a thin end-to-end slice, deployed, so
>    integration risk dies early instead of in Month 7.
> 2. **Consent moves earlier** (Months 3–4). It is the core research contribution and the
>    hardest domain logic; it must not be rushed. Blockchain (Month 6) plugs into an
>    audit-anchor interface that exists from Month 3, so it is an add-on, not a rewrite.

**Rule: a phase is not done until its gate passes. Never start the next phase early.**

---

## M0 — Foundation (Month 1) ✅ DONE, split into sub-milestones by the PO

- **M0.1 — Engineering scaffold ✅ DONE** (2026-07-20): repo structure, docker-compose
  (Postgres+pgvector, Redis, MinIO), FastAPI skeleton, web monorepo shells, tooling, CI,
  Makefile. All checks verified green locally.
- **M0.2 — Domain Foundation & Identity Design ✅ DONE** (2026-07-20): docs/DOMAIN_MODEL.md
  (entities, relationships, RBAC matrix, Health ID design), ADR-011 (Firebase Auth confirmed
  after formal comparison), ADR-012 (Health ID format), ADR-013 (RBAC layers). Design-only.
- **M0.3 — Walking Skeleton ✅ CODE DONE** (2026-08-28, merged as PR #1): Firebase Auth
  integration, Alembic + migrations 0001–0002, Health ID issuance, patient registration/
  profile, patient web login → profile page, OpenAPI-generated api-client, seed system.

**Gate:** a user can register, receive a `PHI-IND-2026-XXXXXXC` ID, log in, and see their
profile in the patient web app, running via one `docker compose up`. CI green on GitHub.
*Status: code merged + pushed (PR #1). The live `docker compose up` + Firebase browser
walk-through are deferred as PO ops/validation tasks (PO decision, 2026-08-28) — they do not
block M2 implementation.*

## M1 — Research & Design (Month 1, parallel with M0)

Literature review (HIE consent models, RAG summarization, blockchain audit trails); Figma screens
for all four clients; conceptual data model review; finalize open decisions (LLM provider,
deployment target, Flutter timing).

**Gate:** Figma flows for the 3 core journeys approved; ADRs 009+ recorded for the open decisions.

## M2 — Backend Core (Month 2) ✅ backend complete (2026-08-29)

`records` module (upload → S3, metadata FHIR-aligned, categorization); `hospitals` +
doctor management with RBAC; async worker skeleton (Redis queue); presigned-URL file access;
seed script for 3 simulated hospitals + synthetic patients.

**Gate:** hospital admin can upload a record for a Health ID; file lands in MinIO/S3; metadata
queryable; RBAC enforced (patient cannot call hospital endpoints); ≥80% coverage on `records`.
*Status: implemented (ADR-014 arq, ADR-015 onboarding; 194 backend tests, records module
88–100% coverage; every gate criterion verified against fakes). The live MinIO/Docker
verification rides on the same deferred PO ops items as the M0.3 gate.*

## M3 — Consent Domain (Month 3) ← CURRENT, backend COMPLETE (2026-09-01)

The heart of PulseOS. `consent` module: request → per-category approve/reject → revoke;
consent-enforcement wired into every non-owner record-read path; append-only access audit log.

**Gate:** full demo flow works across two simulated hospitals: doctor requests → patient approves
per category → doctor reads only approved categories → patient sees audit entry. Revocation cuts
access immediately. Attempted unauthorized reads are denied AND logged.

*Status — backend done, frontend not started (session 014, branch `feature/consent`).* Migration
0004 (five tables), repository/service/HTTP layers, and the records integration are implemented;
268 backend tests, consent module 99–100% coverage. Every gate criterion is exercised over HTTP
in `tests/test_m3_gate.py` across TMH and CMC — including revocation taking effect on the next
read and denials being written to the trail. ADR-016…019 record the decisions taken. **The gate
is not yet demonstrable end to end**: it has no UI, and the two portal journeys it names are
listed under M4 below. Deferred backend findings from the M3 review are in TODO.md.

## M4 — Core Features Complete (Month 4)

**Carried forward from M3** (backend shipped without them): doctor portal — patient search by
Health ID and the request-access flow; patient portal — consent inbox and audit-log view. Both
need two backend pieces that M3 did not build: the category-level existence projection a
clinician uses to *discover* that records exist (SYSTEM_ARCHITECTURE §Consent Flow step 1), and
a patient-facing audit-log endpoint. Notification fan-out for access requests also moves here,
with the `notifications` module.

Hospital portal (request management, doctor management UI, bulk upload); QR identity generation
and scanning; record download via presigned URLs (logged); patient-controlled hide/unhide for
locker records (`is_hidden` is enforced against consent as of M3 but has no endpoint); Flutter
patient app started (auth, profile, consent inbox) — *pending Product Owner decision on timing*.

**Gate:** all three web portals demo the full interoperability story end-to-end with seed data,
including the M3 consent journey.

## M5 — AI Layer (Month 5)

Async OCR pipeline (EasyOCR); chunking + embeddings into pgvector; RAG Health Copilot (scoped to
the requesting patient's own records); AI Patient Summary for doctors (consent-scoped, cached,
invalidated on new records); AI timeline generator; report explainer. PHI-redaction layer before
external LLM calls. See AI_ARCHITECTURE.md.

**Gate:** upload 10 synthetic reports → timeline renders; copilot answers "when was my last blood
test?" correctly; doctor summary generates in <15s warm / cached afterwards; redaction verified.

## M6 — Blockchain Anchoring (Month 6)

**Carried forward from M3:** the `AuditAnchor` interface itself (ADR-004 placed it at M3 so M6
would be a plug-in; it was not built). **Prerequisite before any anchored data exists:** swap the
injected event hasher from SHA-256 to keccak256 per ADR-019 — `audit_logs` is append-only, so
digests written under the old algorithm can never be recomputed.

Solidity consent-anchor contract on Polygon Amoy; `AuditAnchor` interface + `PolygonAuditAnchor`
implementation; reconciliation job (verify DB audit log against chain); graceful degradation
when testnet is down (queue + retry, never block consent flow). See BLOCKCHAIN_ARCHITECTURE.md.

**Gate:** every consent grant/revoke and record access produces an on-chain anchor (hash only);
a verification script proves a tampered DB row is detectable; consent flow still works with the
chain offline.

## M7 — Hardening, Deploy, Paper (Month 7)

E2E test suite over the 3 core journeys; performance pass (LLM caching, N+1 queries); security
review against SECURITY.md checklist; cloud deployment; SRS + final documentation; research paper
draft with the RAG-summary and audit-trail experiments; demo script + fallback recording.

**Gate:** live deployed demo passes the full script twice consecutively; paper draft submitted to
the guide; all docs current.

---

## Phase 2 (only if time remains, in priority order)

Voice assistant → medication reminders → appointment reminders → emergency QR (needs its own
security design — see SECURITY.md §Break-glass) → family accounts.

## Out of Scope (do not build)

ABHA integration, lab/pharmacy/insurance integrations, telemedicine, predictive alerts,
analytics dashboard, regional languages.
