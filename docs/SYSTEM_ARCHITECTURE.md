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
              │  │  notifications (in-app) │  │
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

   Implemented in the uncommitted working tree, ADR-035 (accepted for local implementation): operator-run public-testnet
   submission of batch commitments (verified on a local EVM only; **no public-testnet
   transaction yet**). Not implemented: sealing/anchoring scheduler · OCR/embedding workers
   (ADR-029).
   Out of scope by decision: push/email/SMS notifications (ADR-031 is in-app only).
```

**Deploy units:** `api` (FastAPI) and `worker` (same codebase, arq consumer; currently only a
logging task) run on the host; PostgreSQL, Redis and MinIO run in Docker Compose; Ollama runs
wherever `PULSEOS_OLLAMA_BASE_URL` points. No deployment target is decided yet (ADR-009).

## Module Responsibilities

| Module | Owns | Never does |
|---|---|---|
| `auth` | Firebase token verification (with revocation check), per-request DB account-status and claim/role consistency check, role claims (patient/doctor/hospital_admin/system_admin), RBAC dependencies. Suspending users or revoking tokens has no API (out-of-band) | Business logic |
| `patients` | Patient profile, Health ID issuance (ADR-012), health profile data; patient lookup by Health ID (ADR-021). QR identity is **planned, not built** | Reading record content |
| `records` | Upload, FHIR-aligned metadata (DocumentReference-shaped), categorization, presigned URL issuance, hide/unhide, Synthea FHIR R4 **import** via CLI (proposed ADR-030); consent-gated FHIR R4-shaped Bundle **export** (`GET /records/export/fhir`, proposed ADR-032) of stored FHIR records only. There is no FHIR read/search API | Deciding *whether* access is allowed |
| `consent` | Request → per-category grant/reject → revoke lifecycle; **the consent-enforcement dependency**; append-only audit log with versioned digests; `AuditAnchor` port + local adapter; Merkle batch sealing (manual CLI), database-only reconciliation, and patient-facing verification/proof plus any-role batch verification endpoints (ADR-027) | Storing files or record content |
| `ai` | FHIR-resource ingestion into chunks, deterministic consent-scoped lexical retrieval, clinical assistant and patient copilot answers via the `AnswerGenerator` protocol (Ollama). See AI_ARCHITECTURE.md for what is **not** built (OCR, embeddings, summaries, timeline, explainer, redaction) | Bypassing consent to fetch content |
| `notifications` | In-app notifications for the four consent events (ADR-031): `notifications` table (migration 0008), rows written by `consent` in the same transaction as the consent change, four `/notifications` endpoints for patients and doctors. No push, email, SMS or reminders | Holding audit evidence (notifications are mutable convenience rows) |

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
2. Doctor creates an access request (categories: e.g. CBC, MRI) → `consent` stores it, its audit
   event and an `ACCESS_REQUESTED` in-app notification for the patient in one transaction
   (ADR-031). The patient portal polls for it (no push).
3. Patient approves/rejects per category → `consent` writes decisions, grants, audit events and one
   `CONSENT_APPROVED`/`CONSENT_REJECTED` notification for the doctor in one transaction. The API
   accepts a subset of the requested categories per call; the patient portal currently sends all
   of them at once. Audit events are later sealed into Merkle batches **asynchronously** (v3
   events; ADR-027) — on-chain submission is a separate operator CLI step (ADR-035;
   no public-testnet transaction yet), and no clinical request waits on either.
4. Doctor lists what the grant covers (`GET /granted-records`, ADR-020) — the step that turns an
   approval into reachable record ids. The page is *filtered* by the granted categories, audited
   once as `RECORDS_LISTED`, and discloses a chooser (category, date, hospital), never a document.
5. Doctor reads: every fetch passes `consent.enforce(...)`; allowed reads get metadata and, for
   files, a short-lived presigned URL; every read/download appends an audit event (eligible for
   batch sealing like every v3 event).
6. Revocation deactivates grants immediately and notifies the doctor (`CONSENT_REVOKED`);
   subsequent reads are refused as 404 (never 403, so existence is not disclosed) and logged as
   `ACCESS_DENIED` — including ids the clinician already holds from step 4, because a listing
   permits nothing. AI search, AI answers and the doctor FHIR export re-check grants after their
   reads and discard anything a concurrent revocation removed (AI_ARCHITECTURE.md). A presigned URL
   already issued stays valid until its TTL (default 300 s) and cannot be recalled. Consent-related
   portal screens refresh by polling every 15–30 s and on window focus.

## Cross-Cutting Concerns

- **Async work (ADR-008/014):** uploads return fast and enqueue `record_uploaded`, which only
  logs today; records stay `UPLOADED`. The OCR/embedding pipeline is not built (ADR-029). Batch
  sealing is a manual CLI operation (`scripts/audit_integrity.py seal`, environment-guarded) without a
  scheduler yet (ADR-027).
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
