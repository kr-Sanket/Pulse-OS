# Changelog

All notable changes to PulseOS are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: milestone-based pre-1.0.

## [Unreleased]

### Added
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
