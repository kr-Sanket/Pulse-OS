# System Architecture

> Revised from the original plan's six-microservice design. Rationale: ADR-001.
> The module boundaries below ARE the original service boundaries — the system is
> microservice-ready but deployed as a modular monolith.

## Topology

```
┌────────────────────────── CLIENTS ──────────────────────────┐
│  Flutter App   │  Patient Web  │  Doctor Web  │ Hospital Web │
│  (patient)     │   (React)     │   (React)    │   (React)    │
└───────┬────────┴───────┬───────┴──────┬───────┴──────┬───────┘
        └────────────────┴──── HTTPS ───┴──────────────┘
                             │
              ┌──────────────▼───────────────┐
              │   FastAPI Application (api)   │   ← single deploy unit
              │  auth deps · rate-limit deps  │
              │  ┌─────────────────────────┐  │
              │  │ modules/                │  │
              │  │  auth  patients records │  │
              │  │  consent  ai            │  │
              │  │  (notifications: empty) │  │
              │  └─────────────────────────┘  │
              └──┬─────────┬────────┬────┬────┘
                 │         │        │    │ HTTP (local)
        ┌────────▼──┐ ┌────▼────┐ ┌─▼───────────┐ ┌▼────────────────┐
        │ PostgreSQL│ │  S3 /   │ │ Redis       │ │ Ollama          │
        │ (metadata,│ │  MinIO  │ │ rate limits;│ │ Qwen3:8B        │
        │  consent, │ │ (files, │ │ arq queue ─▶│ │ (generation     │
        │  audit +  │ │ FHIR    │ │ worker:     │ │  only, ADR-028) │
        │  batches, │ │ JSON)   │ │ logging     │ └─────────────────┘
        │  AI chunks│ └─────────┘ │ stub only)  │
        └───────────┘             └─────────────┘

   Planned, not implemented: public-chain submission of batch commitments (ADR-027;
   M6.4+ not authorized) · OCR/embedding workers (ADR-029) · push notifications.
```

**Deploy units:** `api` (FastAPI) and `worker` (same codebase, arq consumer; currently only a
logging task) run on the host; PostgreSQL, Redis and MinIO run in Docker Compose; Ollama runs
wherever `PULSEOS_OLLAMA_BASE_URL` points. No deployment target is decided yet (ADR-009).

## Module Responsibilities

| Module | Owns | Never does |
|---|---|---|
| `auth` | Firebase token verification, role claims (patient/doctor/hospital_admin), RBAC dependencies | Business logic |
| `patients` | Patient profile, Health ID issuance (ADR-012), health profile data; patient lookup by Health ID (ADR-021). QR identity is **planned, not built** | Reading record content |
| `records` | Upload, FHIR-aligned metadata (DocumentReference-shaped), categorization, presigned URL issuance, hide/unhide, Synthea FHIR R4 import (proposed ADR-030) | Deciding *whether* access is allowed |
| `consent` | Request → per-category grant/reject → revoke lifecycle; **the consent-enforcement dependency**; append-only audit log with versioned digests; `AuditAnchor` port + local adapter; Merkle batch sealing and database-only reconciliation (ADR-027) | Storing files or record content |
| `ai` | FHIR-resource ingestion into chunks, deterministic consent-scoped lexical retrieval, clinical assistant and patient copilot answers via the `AnswerGenerator` protocol (Ollama). See AI_ARCHITECTURE.md for what is **not** built (OCR, embeddings, summaries, timeline, explainer, redaction) | Bypassing consent to fetch content |
| `notifications` | **Not implemented** (empty package). Intended: in-app alerts, push, reminders | Anything else |

## Module Isolation Rules (enforced in review)

1. A module's tables are private. Cross-module data access goes through the owning module's
   service interface, never raw queries on foreign tables.
2. Layering inside each module: `router → service → repository`. Domain logic in `service` is
   framework-free (no FastAPI/Request objects, no raw sessions) — this is what makes a future
   microservice split mechanical.
3. **Every** read of record content or metadata-beyond-existence passes through
   `consent.enforce(requester, patient, category)` — one choke point, one place to audit, one
   place to test. (Patients reading their own records pass trivially; it still logs.)
4. External systems (LLM, chain, storage, push) are interfaces with a fake/local implementation
   for tests and local dev.

## The Consent Flow (canonical sequence)

1. Doctor (Hospital B) searches Health ID → `patients` confirms existence; `records` returns only
   *category-level existence* per hospital (no content, no filenames).
2. Doctor creates an access request (categories: e.g. CBC, MRI) → `consent` stores it. The
   patient sees it in their inbox; **no notification is sent** (`notifications` is not built).
3. Patient approves/rejects per category → `consent` writes decisions, grants and audit events in
   one transaction. Audit events are later sealed into Merkle batches **asynchronously** (v3
   events; ADR-027) — nothing is submitted on-chain yet, and no clinical request waits on it.
4. Doctor lists what the grant covers (`GET /granted-records`, ADR-020) — the step that turns an
   approval into reachable record ids. The page is *filtered* by the granted categories, audited
   once as `RECORDS_LISTED`, and discloses a chooser (category, date, hospital), never a document.
5. Doctor reads: every fetch passes `consent.enforce(...)`; allowed reads get metadata and, for
   files, a short-lived presigned URL; every read/download appends an audit event (eligible for
   batch sealing like every v3 event).
6. Revocation deactivates grants immediately; subsequent reads 403 and are logged — including
   ids the clinician already holds from step 4, because a listing permits nothing.

## Cross-Cutting Concerns

- **Async work (ADR-008/014):** uploads return fast and enqueue `record_uploaded`, which only
  logs today; records stay `UPLOADED`. The OCR/embedding pipeline is not built (ADR-029). Batch
  sealing is an operation without a scheduler yet (ADR-027).
- **Caching:** no AI result caching exists. Redis is used for rate limiting (ADR-024) and the job
  queue.
- **Observability:** structured JSON logging with request IDs (no PHI in logs), `/health` +
  `/ready` endpoints. Error tracking (Sentry) is **not implemented**.
- **Config:** 12-factor, env-driven Pydantic settings; `.env.example` is the contract.
- **API surface:** versioned under `/api/v1` — conventions in API_GUIDELINES.md.

## Scaling Path (documented for the paper; not built now)

Monolith → extract `ai` worker pool first (already a separate process) → extract `consent` as a
service if multi-org trust boundaries ever demand it → API gateway becomes a real gateway.
No code rewrite required because of rules 1–2 above.
