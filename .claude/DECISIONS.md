# DECISIONS.md — Architecture Decision Records

> One entry per non-obvious decision. Status: Proposed → Accepted → (Superseded by ADR-NNN).
> New decisions get the next number. Never delete an ADR; supersede it.

---

## ADR-001 — Modular monolith instead of six microservices
**Date:** 2026-07-20 · **Status:** Accepted

**Context:** The original plan specifies six microservices (Auth, Patient, Record, Consent, AI,
Notification) behind an API gateway. The team is 3 students with near-zero ops experience; the
consent flow requires strong transactional consistency between consent grants, record access, and
audit logging.

**Decision:** One FastAPI application ("modular monolith") with six internal modules matching the
original service boundaries. Strict module isolation: modules communicate through service-layer
interfaces, never through each other's tables. Async work (OCR, embeddings, notifications) runs
in separate worker processes consuming a Redis queue — so the *deploy units* are: api, worker,
db, redis, object-store. FastAPI itself is the gateway (auth middleware, rate limiting, routing).

**Why:** Microservices would cost the team distributed tracing, inter-service auth, N pipelines,
network failure modes, and eventual-consistency bugs in the *consent path* — the one place
correctness matters most — while delivering zero benefit at this scale. The résumé/paper value is
preserved: the module boundaries ARE the service boundaries, and the paper can present the
architecture as "microservice-ready." Splitting later is a deploy change, not a rewrite.

**Consequences:** Single DB with per-module schema ownership conventions (DATABASE_DESIGN.md);
one codebase to test; the AI module's heavy dependencies live in the worker image, keeping the
API image slim.

---

## ADR-002 — pgvector instead of FAISS
**Date:** 2026-07-20 · **Status:** Accepted

**Context:** Plan specifies FAISS for RAG vector search. FAISS is an in-process index with no
persistence story, no metadata filtering, and no multi-tenancy — every worker restart means
rebuild, and per-patient scoping must be hand-rolled.

**Decision:** Use PostgreSQL + pgvector. Embeddings live in the same database as record metadata.

**Why:** RAG queries here are always scoped ("records of patient X that requester Y may see") —
that is a SQL `WHERE` clause + vector similarity, which pgvector does natively and FAISS does
not. One less system, durable by default, consent filtering happens in the same query as
retrieval (security property, not just convenience). Corpus size (thousands of chunks, not
millions) is far below where FAISS wins on performance.

**Consequences:** LangChain's pgvector integration is used; the paper describes "consent-scoped
retrieval" — a nice research detail. If scale ever demands it, swap behind the retriever interface.

---

## ADR-003 — Single React monorepo for all three web portals
**Date:** 2026-07-20 · **Status:** Accepted

**Context:** Plan implies three separate React apps (patient, doctor, hospital) built by one
frontend lead, plus a Flutter app.

**Decision:** One pnpm workspace: `web/apps/{patient,doctor,hospital}` + shared packages
`web/packages/{ui,api-client,config}`. The API client is generated from the backend's OpenAPI
spec (type-safe end to end). Vite + React + TypeScript strict + Tailwind.

**Why:** Three separate repos/apps triples dependency upkeep, design drift, and auth plumbing for
one person. Shared UI kit + shared typed client is the only way one frontend lead ships three
portals in the timeline.

**Consequences:** Apps stay separate at the routing/deploy level (a hospital admin never loads
patient code), but share components, tokens, and the client.

---

## ADR-004 — Hash-only on-chain consent anchoring behind a pluggable interface
**Date:** 2026-07-20 · **Status:** Accepted

**Context:** Plan says "consent recorded permanently on blockchain" (Polygon Amoy, Month 6),
while the consent service ships Month 3–4. Public chains must never hold PHI — even encrypted —
and testnets are unreliable and get deprecated.

**Decision:**
1. PostgreSQL (append-only audit table) is the **authoritative** consent/audit store and the only
   read path.
2. An `AuditAnchor` interface exists from Month 3 with a DB-backed implementation; Month 6 adds a
   `PolygonAuditAnchor` that writes `keccak256(canonical_event_json)` + event type + timestamp —
   **hashes only, never identifiers or PHI** on-chain.
3. Anchoring is asynchronous (queued) and non-blocking: chain downtime never delays or blocks a
   consent decision. A reconciliation job detects unanchored events and tampered rows.

**Why:** This is both the secure design (no PHI on a public chain; GDPR/DPDP "right to erasure"
stays satisfiable since only hashes are immutable) and the correct research framing:
*tamper-evidence*, not on-chain storage. It also de-risks the roadmap — blockchain becomes a
plug-in, not a Month-6 rewrite of the consent service.

**Consequences:** The paper's RC-2 experiment is exactly the reconciliation job: tamper a DB row,
show detection. Demo works even if Amoy is down.

---

## ADR-005 — S3-compatible object storage only; Cloudinary dropped
**Date:** 2026-07-20 · **Status:** Accepted

**Context:** Plan lists "AWS S3 / Cloudinary" ambiguously.

**Decision:** S3 API everywhere: MinIO in local docker-compose, real S3 (or Render-compatible
S3 service) in production. Access exclusively via short-lived presigned URLs issued **after** a
consent check. Server-side encryption on. No public buckets.

**Why:** One storage abstraction, identical code local vs prod. Cloudinary is a media-transform
CDN — wrong tool for confidential medical documents.

---

## ADR-006 — FHIR-aligned record metadata
**Date:** 2026-07-20 · **Status:** Accepted

**Context:** The plan defines an interoperability platform but never mentions HL7 FHIR — the
global (and India-ABDM) standard. Health-informatics reviewers will notice.

**Decision:** Model core metadata on FHIR resource shapes: `Patient`, `Practitioner`,
`Organization`, `DocumentReference` (records), `Consent`, `AuditEvent`. We do **not** run a FHIR
server or implement the full spec — we align field names/semantics and record category codes so
an export-to-FHIR mapping is trivial.

**Why:** Near-zero extra cost now; makes RC-4 credible; keeps the "future ABHA integration" claim
honest (ABDM is FHIR-based).

---

## ADR-007 — LLM provider abstraction; Gemini primary; PHI redaction before external calls
**Date:** 2026-07-20 · **Status:** Accepted (provider choice pending PO confirmation)

**Context:** Plan says "Gemini API / OpenAI" interchangeably. Medical text is sent to a third
party; providers differ in cost and API shape.

**Decision:** All LLM/embedding calls go through an internal `LLMProvider` interface. Default
provider: Gemini (free tier fits budget). Before any external call, a redaction step strips
direct identifiers (name, phone, Health ID, address) from prompt content; records are referenced
by opaque tokens. Prompts and redaction rules live in versioned code, not scattered strings.

**Consequences:** Provider swap is config; the redaction layer is a security control AND a
paper-worthy implementation detail.

---

## ADR-008 — Redis-backed async job queue for OCR, embeddings, notifications, anchoring
**Date:** 2026-07-20 · **Status:** Accepted

**Context:** OCR of a scanned PDF takes seconds-to-minutes; embeddings and LLM calls are slow;
the plan has no async story, which would mean request-thread OCR (timeouts, terrible UX).

**Decision:** Redis + a Python task queue (arq or Celery — pick at M2 start; arq preferred for
simplicity with asyncio). Upload returns immediately; processing status is tracked on the record
(`uploaded → processing → indexed | failed`) and surfaced in the UI.

---

## ADR-009 — (placeholder) Deployment target: Render vs AWS
**Status:** Proposed — decide at M1 gate. Recommendation: Render (managed Postgres + Redis,
simplest path for students); AWS only if the team wants the learning curve.

## ADR-010 — (placeholder) Flutter app timing
**Status:** Proposed — decide at M1 gate. Recommendation: start Flutter in Month 4 *after* the
patient web portal stabilizes, reusing the proven API; web portal is the demo-critical patient
surface. Original plan had all four clients in Month 3, which overloads the single frontend lead.
