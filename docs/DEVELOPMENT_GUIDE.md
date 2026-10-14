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
│   │   │   └── notifications/   # empty package (not implemented)
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
  `POSTGRES_PORT=5433` with a matching `PULSEOS_DATABASE_URL`. The host port defaults to 5433 to
  avoid collisions with local PostgreSQL instances on the standard port 5432 (e.g. other projects
  sharing the development machine). If needed, a different `POSTGRES_PORT` can be configured in the
  root `.env` along with a matching `PULSEOS_DATABASE_URL`.
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
| PostgreSQL integration (opt-in) | pytest, `test_audit_batches_postgres.py`, `test_alembic_postgres.py` | Concurrent sealing, UUID ordering, integrity-error classification, migration 0007 on real PostgreSQL |
| Web | vitest (logic tests; no component/DOM tests yet) | Portal view logic |
| Contract (not built) | generated client + schemathesis | OpenAPI spec ↔ implementation |
| E2E (not built; planned M7) | Playwright | The 3 core journeys from CONTEXT.md |

**Opt-in PostgreSQL tests** are skipped unless `PULSEOS_TEST_POSTGRES_URL` names a
`postgresql+asyncpg://` URL for a **disposable** server. They create and drop their own schemas or
databases; never point the variable at a development or real database.

**Recorded results (not a guarantee of the current tree):** 2026-10-11, local — backend **1088
passed, 18 skipped** without the URL; the 18 PostgreSQL tests passed against a disposable
PostgreSQL 16.15 container. Web: 463 tests recorded 2026-09-08 (Session 016), not re-run since.

Rules: consent enforcement gets *negative* tests (wrong role, revoked grant, wrong patient) for
every endpoint that touches records. External services (LLM, chain, S3, FCM) are faked in tests —
never live calls in CI. Coverage target ≥80% on `consent` and `records`; pragmatic elsewhere.

## CI (GitHub Actions)

On every PR and push to `main` (`.github/workflows/ci.yml`), with **no path filters** (docs-only
changes run everything):

- `backend` — `ruff format --check`, `ruff check`, `mypy`, `pytest`. Repo-wide ruff/format/mypy
  findings that predate M6 currently fail the early steps, so this job is not green.
- `backend-postgres` — a disposable PostgreSQL 16 service plus the opt-in PostgreSQL tests; fails if
  any of them is skipped. **Configured locally, not yet run on GitHub** (unpushed as of 2026-10-11).
- `web` — prettier, eslint, `tsc`, vitest.

`make ci` runs the lint, typecheck and test targets locally; it does not run the opt-in PostgreSQL
tests. The API client is regenerated manually (`make api-client`), not in CI. No deployment job
exists (ADR-009 pending).

## Documentation Duties

Code changes that alter behavior/architecture update the **canonical** doc for that fact
(owners listed in `.claude/CLAUDE.md`); other docs link rather than repeat. Non-obvious decisions →
ADR. Session end → SESSION.md + TODO.md.
