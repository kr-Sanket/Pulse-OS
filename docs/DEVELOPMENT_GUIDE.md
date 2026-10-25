# Development Guide

## Repository Layout

```
pulse-os/
├── .claude/                  # AI session memory (start at CLAUDE.md)
├── docs/                     # architecture & process docs
├── backend/
│   ├── app/
│   │   ├── core/             # settings, logging, security deps, errors
│   │   ├── shared/           # cross-module primitives (IDs, pagination, events)
│   │   ├── modules/
│   │   │   ├── auth/         # each module: router.py, service.py,
│   │   │   ├── patients/     #   repository.py, schemas.py, models.py
│   │   │   ├── records/
│   │   │   ├── consent/
│   │   │   ├── ai/
│   │   │   └── notifications/   # in-app consent notifications (ADR-031)
│   │   ├── workers/          # arq worker; only a logging record_uploaded task today
│   │   └── main.py
│   ├── alembic/
│   ├── tests/                # SQLite harness + fakes; opt-in *_postgres.py integration tests
│   └── pyproject.toml        # ruff, mypy(strict), pytest config
├── web/
│   ├── apps/
│   │   ├── patient/
│   │   ├── doctor/
│   │   └── hospital/
│   ├── packages/
│   │   ├── ui/               # shared components + Tailwind tokens
│   │   ├── api-client/       # generated from backend OpenAPI — never hand-edited
│   │   └── config/           # shared tsconfig/eslint
│   └── pnpm-workspace.yaml
├── mobile/                   # Flutter app (starts per ADR-010)
├── contracts/                # placeholder; contract toolchain undecided, nothing built
├── infra/
│   └── docker-compose.yml    # postgres (pgvector image), redis, minio, minio-init — infra only
├── scripts/                  # seed, Synthea import, AI backfill, OpenAPI client generation, audit integrity CLI
└── .github/workflows/        # ci.yml
```

## Local Environment

- Prereqs: Docker, Python ≥3.12 (plain venv + pip; see backend/pyproject.toml), Node ≥20 + pnpm via corepack (CI uses Node 22), (Flutter SDK when relevant).
- **Compose runs infrastructure only:** `make up` starts PostgreSQL, Redis and MinIO (plus a
  bucket-bootstrap container). The API runs on the host with `make dev-api`, the portals with
  `make dev-patient` / `dev-doctor` / `dev-hospital`. The phase-gate wording "`docker compose up`
  brings up a working stack" (CHECKLIST.md) has not been verified as a full-stack start.
- **Database setup:** there is no Makefile target for migrations or seeding. Run
  `cd backend && .venv/bin/alembic upgrade head`, then `backend/.venv/bin/python scripts/seed.py`
  (see scripts/README.md for the Synthea import and AI backfill).
- **Audit integrity CLI:** `backend/.venv/bin/python scripts/audit_integrity.py` provides verifiable
  Merkle integrity inspection and sealing tools (`verify-batch`, `verify-event`, `reconcile`, `seal`).
  The mutating `seal` command is protected by a safety guard requiring `--confirm-env <ENVIRONMENT>`
  matching an explicitly configured `PULSEOS_ENVIRONMENT`; read-only verification commands do not.
  There is no scheduler; sealing happens only when this command is run.
- **Two `.env` files:** the root `.env` (created by `make env` from `.env.example`) is read by
  Docker Compose; the API reads `.env` relative to its working directory, i.e. `backend/.env`
  under `make dev-api` (there is no `backend/.env.example` yet — see TODO.md).
- **PostgreSQL port:** Compose publishes `${POSTGRES_PORT:-5433}:5432`, and `.env.example` sets
  `POSTGRES_PORT=5433` with a matching `PULSEOS_DATABASE_URL`; the backend's built-in default
  (`app/core/config.py`) also targets `localhost:5433`. PostgreSQL itself still listens on 5432
  **inside** the container; 5433 is only the host-side mapping. The host port defaults to 5433 to
  avoid collisions with local PostgreSQL instances on the standard port 5432 (e.g. other projects
  sharing the development machine). If needed, a different `POSTGRES_PORT` can be configured in the
  root `.env` along with a matching `PULSEOS_DATABASE_URL`. An existing `backend/.env` written
  before this change may still name port 5432 — check it if the API cannot reach the database.
  The CI `backend-postgres` job maps its own throwaway service as `5432:5432`; that is separate.
- **AI:** the AI endpoints need a reachable Ollama with the configured model
  (`PULSEOS_OLLAMA_BASE_URL`, `PULSEOS_OLLAMA_MODEL`, default `qwen3:8b`). Set
  `PULSEOS_AI_PROVIDER=fake` to run without a model.
- Configuration only via env vars; `.env.example` lists every variable with a safe default or
  `CHANGEME`. Real `.env` is gitignored. Firebase keys are per-developer (AI uses local Ollama without external API keys).
- Seed script (`scripts/seed.py`) creates the 3 simulated hospitals, the 13-code category
  vocabulary, one demo admin and one demo doctor per hospital, and 3 synthetic patients. It must
  stay idempotent.

## Workflow

1. Pick a task from `.claude/TODO.md` (or the milestone in ROADMAP.md).
2. Branch from `main`: `feat/<module>-<slug>`, `fix/...`, `docs/...`, `chore/...`.
3. Conventional Commits: `feat(consent): add per-category revocation`.
4. PR → CI must pass → review per CONTRIBUTING.md → squash-merge to `main`.
5. `main` is always demoable. If a merge breaks the demo flow, fixing it preempts everything.

## Testing Strategy

| Layer | Tool | What |
|---|---|---|
| Unit + integration | pytest on an in-memory SQLite harness (`tests/support.py`) | Domain logic, routers→DB, migrations up/down (`test_alembic.py`) |
| PostgreSQL integration (opt-in) | pytest, `test_audit_batches_postgres.py`, `test_alembic_postgres.py`, `test_consent_postgres.py` | Concurrent sealing, UUID ordering, integrity-error classification, migration 0007, concurrent duplicate consent requests/approvals (with no-lock controls), the filename column limit — on real PostgreSQL. All three files are in the CI `backend-postgres` job's explicit list |
| Web | vitest (mostly logic tests; a few `renderToString` component tests; no jsdom/DOM tests) | Portal view logic, API modules, shared hooks |
| Contract (not built) | generated client + schemathesis | OpenAPI spec ↔ implementation |

**No E2E infrastructure.** There is no Playwright/Cypress workspace, configuration, synthetic E2E
authentication or E2E Docker setup; the experimental E2E work was removed (`281439c`) and is not
planned for the final review. Cross-portal journeys are verified by the backend HTTP tests (e.g.
`tests/test_m3_gate.py`) plus manual walk-throughs.

**Opt-in PostgreSQL tests** are skipped unless `PULSEOS_TEST_POSTGRES_URL` names a
`postgresql+asyncpg://` URL for a **disposable** server. They create and drop their own schemas or
databases; never point the variable at a development or real database. A throwaway local
server that touches nothing else (no volume, removed on stop):
`docker run -d --rm --pull never --name pulseos-pgtest -e POSTGRES_USER=pulseos_scratch
-e POSTGRES_PASSWORD=<throwaway> -e POSTGRES_DB=pulseos_scratch -p 127.0.0.1:55432:5432
--tmpfs /var/lib/postgresql/data pgvector/pgvector:pg16`, then `docker stop pulseos-pgtest`.

**Recorded results (not a guarantee of the current tree):** 2026-10-25, `0ea4bac` plus the
Session 021 changes, local only — backend **1351 passed, 26 skipped** without the
URL (the 25 skips are the opt-in PostgreSQL tests, not run locally); strict `mypy` clean (173
source files); `ruff check` and `ruff format` clean; web **689 passed** (hospital 252, patient 229,
doctor 158, ui 33, api-client 17); web formatting, linting, typechecking and `pnpm build` clean.
The last CI result on record is GitHub Actions run #17 for `d09d721`, reported **GREEN** across all
jobs (user-provided evidence; logs not stored in repository); later commits have no CI result yet.

Rules: consent enforcement gets *negative* tests (wrong role, revoked grant, wrong patient) for
every endpoint that touches records. External services (LLM, chain, S3, FCM) are faked in tests —
never live calls in CI. Coverage target ≥80% on `consent` and `records`; pragmatic elsewhere.

## CI (GitHub Actions)

On every PR and push to `main` (`.github/workflows/ci.yml`), with **no path filters** (docs-only
changes run everything):

- `backend` — `ruff format --check`, `ruff check`, `mypy`, `pytest`. All four steps clean.
- `backend-postgres` — a disposable PostgreSQL 16 service running the opt-in PostgreSQL tests
  (`test_audit_batches_postgres.py`, `test_alembic_postgres.py`, `test_consent_postgres.py`).
  Must run all 26 tests with none skipped (the job fails on any skip); last reported passing in run #17.
- `web` — prettier, eslint, `tsc`, vitest, then **Generated api-client is current** (regenerates
  `schema.ts` from the committed `openapi.json` and fails on `git diff --exit-code`) and
  **Production build** (`pnpm build`).
- There is no E2E job (see Testing Strategy).

`make ci` runs the lint, typecheck and test targets locally; it does not run the opt-in PostgreSQL
tests. The API client is regenerated manually (`make api-client` / `scripts/generate-api-client.sh`);
CI only checks that the committed `schema.ts` matches the committed spec. There is no backend
spec-drift check (re-exporting `openapi.json` in CI) because there is no Python lockfile, so CI
could resolve different FastAPI/Pydantic versions. No deployment job exists (ADR-009 pending).

## Documentation Duties

Code changes that alter behavior/architecture update the **canonical** doc for that fact
(owners listed in `.claude/CLAUDE.md`); other docs link rather than repeat. Non-obvious decisions →
ADR. Session end → SESSION.md + TODO.md.
