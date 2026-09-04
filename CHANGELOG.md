# Changelog

All notable changes to PulseOS are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: milestone-based pre-1.0.

## [Unreleased]

### Added
- **M4.3 `GET /api/v1/granted-records` (ADR-020)** — the step the consent flow was missing: a
  clinician holding a grant could not obtain a single `record_id`, because `GET /records` is
  patient/hospital-only, `/records/existence` returns no identifiers, `/consent-grants` is
  patient-only, and record ids are random. DOCTOR-only and ACTIVE-only; the page is *filtered*
  by the categories consent reports as granted and returns a chooser projection — id, category,
  origin, date of service, uploading hospital, created at — with `grantedCategories` beside it so
  "nothing was approved" is distinguishable from "what was approved is empty". Filename,
  description, size, content type and processing status are withheld and stay on the single
  authorized read. Hidden records never appear. **The listing permits nothing:** every record
  opened from it still crosses `consent.enforce` once, so an id survives revocation by exactly
  zero seconds. Audited as **one** event per request — `RECORDS_LISTED`, or `ACCESS_DENIED` when
  nothing is in scope — never one per row. Backend tests 328 → 368.
- **M4.2 Doctor portal — first vertical slice:** login → dashboard → patient search. The
  dashboard renders the clinician's own profile from `GET /doctors/me` (name, hospital,
  ACTIVE/PENDING/SUSPENDED badge, registration number) and a search card; `/patients` searches by
  Pulse Health ID against `GET /records/existence` and lists the available record categories —
  names only, no counts, filenames, hospitals or dates. A non-ACTIVE clinician sees their real
  status and a disabled search (ADR-015). Access requests are **not** part of this slice. 16 tests.
- **`@pulseos/ui` is now the shared portal foundation** (ADR-003: "share components, tokens", and
  do not triple auth plumbing). The auth layer (`provider`, `firebase`, `firebaseAuthProvider`,
  `devMockAuthProvider`, `AuthContext`), `ProtectedRoute`, `LoadingScreen`, `apiResult`,
  `useApiResource`, `cn`, `initialsFor` and **`tokens.css`** moved out of the patient app; both
  portals now compile the same palette, so the surfaces cannot drift. shadcn primitives stay
  per app deliberately — that is the shadcn model, and sharing them would drag the whole UI kit
  into the package. Behaviour-neutral: the patient app's 111 tests and its CSS hash are unchanged.
- **M4.1 `GET /api/v1/records/existence`** — the clinician-facing record-existence projection
  (SYSTEM_ARCHITECTURE §Consent Flow step 1). DOCTOR-only and ACTIVE-only; answers
  `{items:[{code, displayName}]}` for a Pulse Health ID and nothing else — no record ids,
  filenames, hospitals, dates, descriptions or counts. Hidden records are excluded. One grouped
  SQL query. It deliberately does not pass `consent.enforce`, which cannot answer a
  per-record question before any grant exists; the ADR-015 ACTIVE check is the relationship this
  module *can* decide, and every read past discovery still crosses the choke point once. Backend
  tests 300 → 320.
- **Patient-facing identity projection** — `records.directory.StaffDirectoryService` publishes
  display-safe staff facts (full name, specialty, hospital name; no identifiers, no employment
  status), consumed by consent through a `StaffDirectory` protocol. Batched by construction: a
  collection in, a mapping out, one statement per identity kind per page, with an N+1 guard test
  that counts SQL statements. Adds `requester` to the access-request listings, `grantee` to the
  grants listing and `actor` to audit entries, so patients read names instead of UUIDs.
- **`GET /api/v1/consent-grants`** — the patient's grant history (revoked and expired included),
  each row carrying a derived `status` (ACTIVE / REVOKED / EXPIRED) read with the same predicate
  enforcement applies, so the listing can never call a grant active that a read would refuse.
- **`GET /api/v1/audit-logs`** — the patient-facing append-only trail, keyset-paginated on the
  application-assigned `occurred_at`. Exposes the action, the actor and the role they held, the
  target (category by code), the event time and the tamper-evidence digest; deliberately omits
  `patientId`, `requestContext` and the storage timestamp.
- **M4 Patient portal integration:** all seven pages (Dashboard, Medical Records, Consent
  Requests, Active Grants, Audit History, Profile, Settings) rebuilt against the real API, each
  as `src/<feature>/{api,view,use*}` with dumb components and all mapping in `view.ts`. Records
  supports listing, detail, presigned download and locker upload; Consent supports per-category
  approve/reject without a refetch; Grants groups one approval's rows into one card and revokes
  them together; Audit renders the trail with a page-scoped summary that says so. Every mock
  module was deleted except `src/data/settings.ts`. Web tests → 131.

### Fixed
- **An unconfigured Firebase project reported itself as a client error.** `firebase_admin`
  signals a missing project id with a bare `ValueError` — the same type it raises for a
  malformed token — so `FirebaseAuthProvider` mapped it to `InvalidTokenError` and answered
  **401 "Invalid authentication token."**, blaming the caller for the server's own missing
  configuration, while `core/config.py` promised 503. `_get_app` now verifies the SDK resolved a
  project and raises `AuthProviderUnavailableError` → **503**, logging which variable to set.

- **M3 Consent Domain (backend):** the `consent` module — access request → per-category
  approve/reject → revoke, with `consent.enforce()` attached to every non-owner record read.
  Migration 0004 adds five tables: `consent_requests`, `consent_request_categories`,
  `consent_decisions` (immutable), `consent_grants` (what enforcement reads, O(1) by index),
  and the append-only `audit_logs`. Two invariants are enforced by the database rather than by
  code: a decision may only answer a category the request asked for (composite foreign key),
  and an approval spawns exactly one grant (unique `decision_id`). Six endpoints under
  `/api/v1/access-requests` and `/api/v1/consent-grants`. Every consent decision, revocation,
  allowed read and **denied** read appends an audit event in the same transaction as the action
  (`ACCESS_DENIED` added to the vocabulary, ADR-018), hashed for later on-chain anchoring
  (SHA-256 for now, ADR-019). `records` gained a published identity/vocabulary seam
  (`records/directory.py`) and a `ConsentEnforcer` port, making the records ⇄ consent dependency
  explicit and cycle-free (ADR-016); audited read failures return their RFC 7807 response rather
  than raising it, so a refusal is durably recorded (ADR-017). Patient-controlled visibility is
  honoured: a hidden record is invisible to a clinician holding a valid grant, and unchanged for
  its owner and its uploading hospital. Hospital-admin own-upload reads keep their M2 behaviour
  (ADR-013 layer 2). Backend tests 194 → 268; the ROADMAP M3 gate is walked over HTTP across two
  simulated hospitals. **Not included:** notifications fan-out, the `AuditAnchor` interface, the
  clinician-facing record-existence projection, a patient audit-log endpoint, and all M3
  frontend work.
- **M2 Backend Core (records module):** hospital + admin and doctor self-registration with
  System-Admin hospital verification and admin-managed doctor activation (ADR-015);
  `MedicalRecord` (FHIR DocumentReference-aligned) with migration 0003; multipart record
  upload → S3/MinIO behind an `ObjectStorage` port (hospital-for-Health-ID and patient
  locker flows); relationship-scoped metadata listing (cursor pagination, category filter)
  and short-lived presigned download URLs; arq chosen as the job queue (ADR-014) with a
  `JobQueue` port, worker entry point (`arq app.workers.main.WorkerSettings`) and a
  no-op `record_uploaded` task; seed extended with demo hospital staff and 3 synthetic
  patients (pinned valid Health IDs). Doctors deliberately have **no** record access until
  the consent module (M3). Backend tests 106 → 194.
- **M0.3 Walking Skeleton** (shipped in PR #1): auth module (Firebase port, role gates),
  patients module (registration, ADR-012 Health ID issuance, profile), migrations 0001–0002,
  DB/logging/RFC 7807 plumbing, OpenAPI-generated api-client, patient web login → profile,
  idempotent seed system.
- M0.2 Domain Foundation & Identity Design (docs-only): `docs/DOMAIN_MODEL.md` (entities,
  relationships, RBAC matrix, Health ID design, open decisions OD-1…3) and ADR-011 (Firebase
  Auth evaluation), ADR-012 (Health ID format), ADR-013 (RBAC layers).

### Changed
- Milestone renumbering after the M0 split: the walking skeleton is now **M0.3** (M0.2 became
  the domain design milestone). Stale M0.2 references in scaffold comments updated accordingly.

## [0.1.0] — 2026-07-20 · M0.1 Engineering Workspace & Project Scaffold

### Added
- Repository structure per approved architecture: `backend/`, `web/`, `mobile/`, `contracts/`, `infra/`, `scripts/`, `.github/`, `docs/`, `.claude/`.
- Backend skeleton: FastAPI app factory with `/health` liveness endpoint, env-driven Pydantic settings (`PULSEOS_` prefix), module packages for the six monolith modules (ADR-001), placeholder tests.
- Backend tooling: Ruff (lint + format, replaces Black — see docs/CONTRIBUTING.md), mypy strict with pydantic plugin, pytest (+coverage), all configured in `pyproject.toml`.
- Web monorepo: pnpm workspace with three Vite/React app shells (patient :5173, doctor :5174, hospital :5175) and shared packages `@pulseos/config` (tsconfig bases), `@pulseos/ui` (with vitest wiring), `@pulseos/api-client` (placeholder until OpenAPI generation lands).
- Web tooling: ESLint 9 flat config + typescript-eslint + react-hooks, Prettier, TypeScript strict.
- Local infrastructure: `infra/docker-compose.yml` — PostgreSQL 16 with pgvector (ADR-002), Redis 7, MinIO + one-shot bucket bootstrap; named volumes, dedicated network, healthchecks, safe local defaults.
- Root tooling: `.editorconfig`, `.env.example` (documented, milestone-annotated), `Makefile` (env/up/down/install/dev-*/lint/typecheck/test/ci), updated `.gitignore`.
- CI: GitHub Actions workflow — backend job (ruff format check, ruff lint, mypy, pytest) and web job (prettier check, eslint, tsc, vitest) with dependency caching.
- README rewritten as a self-sufficient developer quickstart.

### Notes
- No business logic, database schema, API endpoints (beyond `/health`), auth, frontend pages, AI, or blockchain code — by design; those begin at the walking skeleton (now M0.3) per `.claude/ROADMAP.md`.
- Alembic wiring deferred to the walking skeleton (now M0.3, first migration), since M0.1 forbids schema work.
