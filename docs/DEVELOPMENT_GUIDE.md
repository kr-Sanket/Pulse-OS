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
├── scripts/                  # seed, Synthea import, AI backfill, OpenAPI client generation
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

**Recorded results (not a guarantee of the current tree):** 2026-10-15, `72b55e2` plus the
uncommitted authorization and audit correctness changes, local — backend **1165 passed,
25 skipped** without the URL (the 25 skips are the opt-in PostgreSQL tests) and **1190 passed,
0 skipped** with it, against a disposable PostgreSQL 16.15 container; web **550 passed**
(patient 184, hospital 162, doctor 156, ui 31, api-client 17). These are local runs, not
GitHub Actions results.

Rules: consent enforcement gets *negative* tests (wrong role, revoked grant, wrong patient) for
every endpoint that touches records. External services (LLM, chain, S3, FCM) are faked in tests —
never live calls in CI. Coverage target ≥80% on `consent` and `records`; pragmatic elsewhere.

## CI (GitHub Actions)

On every PR and push to `main` (`.github/workflows/ci.yml`), with **no path filters** (docs-only
changes run everything):

- `backend` — `ruff format --check`, `ruff check`, `mypy`, `pytest`. The findings recorded on
  2026-10-11 were fixed in `10bec8f`/`4d8e181`/`2cb0851`; the ruff findings `15b2d1b` added to
  four test files are fixed in the working tree (uncommitted). Local run 2026-10-15: all four
  steps clean. **At `72b55e2` as pushed, this job fails at `ruff format --check`** until that fix
  is committed.
- `backend-postgres` — a disposable PostgreSQL 16 service plus the opt-in PostgreSQL tests
  (`test_audit_batches_postgres.py`, `test_alembic_postgres.py`, `test_consent_postgres.py` — the
  file list is explicit; the third was added 2026-10-15, uncommitted); fails if any is skipped.
  The same command passes locally against a disposable PostgreSQL 16.15 (25 passed, 0 skipped). **At `72b55e2` as pushed, two `test_alembic_postgres.py` tests fail**
  (they upgraded to `head` and expected `0007`, which stopped being head when `15b2d1b` added
  0008); pinned to `0007` in the working tree, uncommitted. GitHub run results have not been
  checked here.
- `web` — prettier, eslint, `tsc`, vitest. All clean locally at `72b55e2` (2026-10-14).
- There is no E2E job (see Testing Strategy).

`make ci` runs the lint, typecheck and test targets locally; it does not run the opt-in PostgreSQL
tests. The API client is regenerated manually (`make api-client`), not in CI. No deployment job
exists (ADR-009 pending).

## Documentation Duties

Code changes that alter behavior/architecture update the **canonical** doc for that fact
(owners listed in `.claude/CLAUDE.md`); other docs link rather than repeat. Non-obvious decisions →
ADR. Session end → SESSION.md + TODO.md.
