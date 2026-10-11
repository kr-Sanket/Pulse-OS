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
*Status (2026-09-08): partially met and still open. 25 ADRs are recorded (ADR-011…025), but
**ADR-009 (deployment target) and ADR-010 (Flutter timing) remain placeholders**, and both now
block later work — ADR-009 gates pre-auth rate limiting and all of M7's deployment. No Figma
exists: the three portals were built without it, so that item is now documentation of what was
built as much as design of what will be. The literature review has not been done.*

## M2 — Backend Core (Month 2) ✅ backend complete (2026-08-29)

`records` module (upload → S3, metadata FHIR-aligned, categorization); `hospitals` +
doctor management with RBAC; async worker skeleton (Redis queue); presigned-URL file access;
seed script for 3 simulated hospitals + synthetic patients.

**Gate:** hospital admin can upload a record for a Health ID; file lands in MinIO/S3; metadata
queryable; RBAC enforced (patient cannot call hospital endpoints); ≥80% coverage on `records`.
*Status: implemented (ADR-014 arq, ADR-015 onboarding; 194 backend tests, records module
88–100% coverage; every gate criterion verified against fakes). The live MinIO/Docker
verification rides on the same deferred PO ops items as the M0.3 gate.*

## M3 — Consent Domain (Month 3) ✅ COMPLETE (backend 2026-09-01; gate criteria met in code 2026-09-08)

The heart of PulseOS. `consent` module: request → per-category approve/reject → revoke;
consent-enforcement wired into every non-owner record-read path; append-only access audit log.

**Gate:** full demo flow works across two simulated hospitals: doctor requests → patient approves
per category → doctor reads only approved categories → patient sees audit entry. Revocation cuts
access immediately. Attempted unauthorized reads are denied AND logged.

*Status (2026-09-08) — backend and both halves of the UI are done.* Migration 0004 (five tables),
repository/service/HTTP layers, and the records integration are implemented. Every gate criterion
is exercised over HTTP in `tests/test_m3_gate.py` across TMH and CMC — including revocation taking
effect on the next read and denials being written to the trail. ADR-016…019 record the decisions
taken. The patient portal renders the consent inbox, active grants and the audit trail; the doctor
portal now *creates* access requests and reads granted records, which was the one missing link.
**Every gate criterion is therefore met in code.** What remains is the same PO ops/validation task
that the M0.3 and M2 gates carry: a live browser walk-through against running infrastructure.
Deferred backend findings are in TODO.md.

## M4 — Core Features Complete (Month 4) — substantially done, status 2026-09-08 (`ea2ebd5`)

**Carried forward from M3, all shipped:**

- ✅ Patient portal: consent inbox, active grants and audit-log view, all integrated.
- ✅ `GET /api/v1/audit-logs` — the patient-facing trail.
- ✅ `GET /api/v1/consent-grants` — the grant listing, with a derived ACTIVE/REVOKED/EXPIRED state.
- ✅ `GET /api/v1/records/existence` — the category-level existence projection a clinician uses
  to discover that records exist (SYSTEM_ARCHITECTURE §Consent Flow step 1), plus the batched
  staff identity projection that lets patients read names instead of UUIDs.
- ✅ `GET /api/v1/granted-records` (ADR-020) — the clinician-scoped record listing that turns an
  approval into reachable record ids (SYSTEM_ARCHITECTURE §Consent Flow step 4). Grant-filtered,
  chooser-only disclosure, one audit event per request; `enforce` still rules on every read.
- ✅ **Doctor portal, complete consent workflow**: login → register → dashboard → patient search
  by Health ID → request access per category → sent requests → granted records → record detail →
  download. Slice 2 (the request-access flow) closed the M3 gate.

**Also shipped in M4, beyond what M3 carried forward:**

- ✅ **Hospital portal**: shell + login, self-registration, doctor management (activate/
  deactivate), uploaded-records listing and detail, patient lookup by Health ID (ADR-021) with
  upload confirmation, and a hospital-scoped audit history.
- ✅ **Hospital audit attribution** (migration 0005, ADR-022/023/025): hospitals emit audit events
  for their own reads; events carry the actor's hospital *as at the time*; a versioned audit-hash
  scheme; the patient's trail reads historical attribution rather than present employment.
- ✅ **Authenticated rate limiting** (ADR-024) on the four Health-ID/discovery surfaces — closes
  finding M3-D for authenticated abuse. Pre-auth throttling is still open (see TODO).
- ✅ **Synthea FHIR R4 Phase A ingestion**: 10 pinned patients, 889 records, sanitized raw FHIR to
  object storage behind the audited consent path. Phase B is deferred (TODO §1b).
- ✅ **Patient record browsing**: clinical-date ordering, newest/oldest sort, server-side search,
  category filter, cursor pagination and Load more.
- ✅ **Patient audit history**: grouped hospital → actor → events, own-activity filter, Load more.
- ✅ **Patient profile editing**: `PATCH /api/v1/patients/me` (the API's first PATCH).
- ✅ **Patient record hide/unhide**: `PATCH /api/v1/records/{id}/visibility`, any record the
  patient owns; removes it from every grantee surface and revokes nothing.
- ✅ Record download via presigned URLs, audited, in all three portals.

**Still open in M4:**

- ⬜ **`notifications` module** — in-app notification on request created / decided / revoked, via
  arq. Still an empty `__init__.py`; access requests arrive silently.
- ⬜ **QR identity generation and scanning.**
- ⬜ Hospital portal **bulk upload** (single-record upload is done) and **request management on
  behalf of their doctors** (the `⭕` dual-consent cell in DOMAIN_MODEL §3) — both were in this
  milestone's original scope and neither is built.
- ⬜ **SYSTEM_ADMIN provisioning** — no code path creates one, so `POST /hospitals/{hid}/verify`
  has no reachable caller and a self-registered hospital stays `PENDING`. Masked in demos because
  the three seeded hospitals are already VERIFIED.
- ⬜ Flutter patient app (auth, profile, consent inbox) — *pending Product Owner decision on
  timing (ADR-010 is still a placeholder); `mobile/` is a README.*

**Gate:** all three web portals demo the full interoperability story end-to-end with seed data,
including the M3 consent journey. *Status (as of 2026-09-08, `ea2ebd5`): the portals and the
journey exist and were covered by 653 backend / 463 web tests at that date; the gate's live demo
run is the same PO ops task as M0.3 and M2.*

## M5 — AI Layer (Month 5)

Async OCR pipeline (EasyOCR); chunking + embeddings into pgvector; RAG Health Copilot (scoped to
the requesting patient's own records); AI Patient Summary for doctors (consent-scoped, cached,
invalidated on new records); AI timeline generator; report explainer. PHI-redaction layer before
external LLM calls. See AI_ARCHITECTURE.md.

**Gate:** upload 10 synthetic reports → timeline renders; copilot answers "when was my last blood
test?" correctly; doctor summary generates in <15s warm / cached afterwards; redaction verified.

*Status (2026-10-11) — partially built, on a different design than planned; gate **not met**.*
Built (commits `a7df8b4`…`c95494a`, 2026-10-04 to 2026-10-10): FHIR-resource ingestion into
`ai_documents`/`ai_chunks` (migration `aedb0169a4eb`) via the Synthea import and
`scripts/backfill_ai.py`; deterministic, consent-scoped lexical retrieval (ADR-029); context
assembly; answer generation through the `AnswerGenerator` protocol with **local Ollama (Qwen3:8B)
as the only provider** (ADR-028, Gemini removed); three endpoints (clinician search, clinician
answer, patient copilot answer) with the `ai_generate` rate limit and `SUMMARY_GENERATED`
auditing; the doctor `AIAssistantPanel` and patient `HealthCopilotPanel`. **Not built:** OCR of
uploads and the worker pipeline, embeddings/pgvector, cached patient summary, timeline, report
explainer, redaction layer. Hidden-record fix (2026-10-11): clinician retrieval now excludes
patient-hidden records in the query; the patient copilot keeps owner access (AI_ARCHITECTURE.md).
It was validated locally on SQLite and a disposable PostgreSQL 16.15; GitHub CI has not run on
it. Still open: the clinician search endpoint is neither audited nor rate-limited
(SECURITY.md). The gate as written (timeline, summary, redaction, uploaded reports) needs either
the missing features or a PO-approved restatement; no evaluation results exist (RC-3).

## M6 — Blockchain Anchoring (Month 6)

**Carried forward from M3:** the `AuditAnchor` interface itself (ADR-004 placed it at M3 so M6
would be a plug-in) — since built: the port, `LocalChainAuditAnchor` and migration 0006
(`b17c2f0`). **Prerequisite before any anchored data exists — done (M6.1):** new audit events
are hashed with Keccak-256 as `hash_version` 3 per ADR-019's resolution; v1/v2 rows keep their
SHA-256 digests (`audit_logs` is append-only) and are verifiable locally only.

**Architecture: ADR-027 — Merkle-batched anchoring of verified v3 events**, one opaque 32-byte
commitment per batch on-chain (amends ADR-004 decision 2; no per-event on-chain anchoring). Stages:

- **M6.1 — done:** Keccak-256 audit digests as `hash_version` 3 (ADR-019 Resolution).
- **M6.2 / M6.2.1 — done:** `consent/merkle.py` reference implementation, pinned vectors, proof
  verification against trusted index/count.
- **M6.3 — committed in `e3c0fe1` (PostgreSQL integration tests in `1ce4c14`); M6.1–M6.3
  accepted with deferred items:** additive batch and membership tables (migration 0007);
  deterministic sealing (max 256 leaves, 300 s interval, 900 s backlog threshold — all
  configurable); commitment computation with pinned vectors; database-only reconciliation; v3
  events refused by the old per-event workflow; migration and concurrency/idempotency tests. No
  chain, scheduler, API or CLI. Validation (2026-10-11): full backend run 1088 passed, 18 skipped;
  the 18 opt-in PostgreSQL tests (batch sealing/classification and migration 0007) passed against
  a disposable scratch PostgreSQL 16, and CI job `backend-postgres` runs them (not yet run on
  GitHub).
- **M6.4 — not authorized.**
- **Later (deferred by ADR-027):** receipts and retry-safe submission; Solidity commitment registry
  and `PolygonAuditAnchor` on Amoy; scheduler; reconciliation CLI with chain-side checks; integrity
  API/frontend; graceful degradation when the testnet is down (never block consent flow). See
  BLOCKCHAIN_ARCHITECTURE.md.

**Gate:** every v3 consent grant/revoke and record-access event is covered by a batch whose
commitment is anchored on-chain (hash only, ADR-027); a verification script proves a tampered DB
row is detectable; consent flow still works with the chain offline. **Gate status: not complete**
— on-chain batch submission, receipts and chain-side verification remain deferred.

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
