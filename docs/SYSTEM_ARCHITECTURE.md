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
              │  auth middleware · rate limit │
              │  ┌─────────────────────────┐  │
              │  │ modules/                │  │
              │  │  auth  patients records │  │
              │  │  consent  ai  notifs    │  │
              │  └─────────────────────────┘  │
              └──┬──────────┬─────────┬───────┘
                 │          │         │ enqueue
        ┌────────▼──┐  ┌────▼────┐ ┌──▼──────────────────┐
        │ PostgreSQL│  │  S3 /   │ │ Redis ─▶ Worker(s)  │
        │ + pgvector│  │  MinIO  │ │ OCR · embed · LLM · │
        │ (metadata,│  │ (files) │ │ notify · anchoring  │
        │  consent, │  └─────────┘ └──────────┬──────────┘
        │  audit,   │                         │ hashes only
        │  vectors) │              ┌──────────▼──────────┐
        └───────────┘              │ Polygon Amoy        │
                                   │ (audit anchor)      │
                                   └─────────────────────┘
```

**Deploy units:** `api` (FastAPI), `worker` (same codebase, queue consumer), PostgreSQL, Redis,
object store. That's it.

## Module Responsibilities

| Module | Owns | Never does |
|---|---|---|
| `auth` | Firebase token verification, role claims (patient/doctor/hospital_admin), RBAC dependencies | Business logic |
| `patients` | Patient profile, Health ID issuance, QR payload, health profile data | Reading record content |
| `records` | Upload, FHIR-aligned metadata (DocumentReference-shaped), categorization, presigned URL issuance, processing status | Deciding *whether* access is allowed |
| `consent` | Request → per-category grant/reject → revoke lifecycle; **the consent-enforcement dependency**; append-only audit log; `AuditAnchor` interface | Storing files or record content |
| `ai` | OCR pipeline, chunking/embedding, consent-scoped RAG retrieval, summaries, timeline, explainer, copilot; `LLMProvider` interface; redaction | Bypassing consent to fetch content |
| `notifications` | Push (FCM), in-app alerts, reminder scheduling | Anything else |

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
2. Doctor creates an access request (categories: e.g. CBC, MRI) → `consent` stores it,
   `notifications` pushes to patient.
3. Patient approves/rejects per category → `consent` writes grants + audit events →
   `AuditAnchor.anchor(event)` enqueued (async, non-blocking).
4. Doctor reads: every fetch passes `consent.enforce(...)`; allowed reads get metadata and, for
   files, a short-lived presigned URL; every read/download appends an audit event (also anchored).
5. Revocation deactivates grants immediately; subsequent reads 403 and are logged.

## Cross-Cutting Concerns

- **Async pipeline (ADR-008):** uploads return fast; worker runs OCR → chunk → embed → index;
  record status `uploaded → processing → indexed | failed` is visible to clients.
- **Caching:** AI summaries cached per (patient, requester-scope, records-version); invalidated
  when a new record is indexed. Redis for rate limiting and hot lookups.
- **Observability:** structured JSON logging with request IDs (no PHI in logs), `/health` +
  `/ready` endpoints, Sentry (free tier) for error tracking.
- **Config:** 12-factor, env-driven Pydantic settings; `.env.example` is the contract.
- **API surface:** versioned under `/api/v1` — conventions in API_GUIDELINES.md.

## Scaling Path (documented for the paper; not built now)

Monolith → extract `ai` worker pool first (already a separate process) → extract `consent` as a
service if multi-org trust boundaries ever demand it → API gateway becomes a real gateway.
No code rewrite required because of rules 1–2 above.
