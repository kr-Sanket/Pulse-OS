# Development Guide

## Repository Layout (target — created at M0)

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
│   │   │   └── notifications/
│   │   ├── workers/          # queue consumers (OCR, embed, anchor, notify)
│   │   └── main.py
│   ├── alembic/
│   ├── tests/                # mirrors app/ structure; conftest with fakes
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
├── contracts/                # Solidity + Hardhat (M6)
├── infra/
│   ├── docker-compose.yml    # pg+pgvector, redis, minio, api, worker
│   └── deploy/               # Render/AWS config
├── scripts/                  # seed data, OpenAPI client generation, chain reconciliation
└── .github/workflows/        # ci.yml
```

## Local Environment

- Prereqs: Docker, Python ≥3.12 (plain venv + pip; see backend/pyproject.toml), Node ≥20 + pnpm via corepack (CI uses Node 22), (Flutter SDK when relevant).
- `docker compose up` must bring up a fully working local stack from a clean checkout — this is
  a standing acceptance criterion (see CHECKLIST.md phase gate).
- Configuration only via env vars; `.env.example` lists every variable with a safe default or
  `CHANGEME`. Real `.env` is gitignored. Firebase/Gemini keys are per-developer.
- Seed script (`scripts/seed.py`) creates the 3 simulated hospitals, demo doctors, and synthetic
  patients — the same data the demo uses. It must stay idempotent.

## Workflow

1. Pick a task from `.claude/TODO.md` (or the milestone in ROADMAP.md).
2. Branch from `main`: `feat/<module>-<slug>`, `fix/...`, `docs/...`, `chore/...`.
3. Conventional Commits: `feat(consent): add per-category revocation`.
4. PR → CI must pass → review per CONTRIBUTING.md → squash-merge to `main`.
5. `main` is always demoable. If a merge breaks the demo flow, fixing it preempts everything.

## Testing Strategy

| Layer | Tool | What |
|---|---|---|
| Unit | pytest | Service-layer domain logic with fake repositories/providers; consent rules exhaustively |
| Integration | pytest + testcontainers (or compose services) | Router→DB paths; migrations apply cleanly; presigned URL issuance |
| Contract | generated client + schemathesis (later) | OpenAPI spec ↔ implementation |
| Web | vitest + testing-library | Shared UI components; consent inbox logic |
| E2E (M7) | Playwright | The 3 core journeys from CONTEXT.md |

Rules: consent enforcement gets *negative* tests (wrong role, revoked grant, wrong patient) for
every endpoint that touches records. External services (LLM, chain, S3, FCM) are faked in tests —
never live calls in CI. Coverage target ≥80% on `consent` and `records`; pragmatic elsewhere.

## CI (GitHub Actions)

On every PR and push to `main`:
backend → ruff, mypy (strict), pytest · web → eslint, `tsc --noEmit`, vitest ·
docs-only changes skip heavy jobs. Deployment job added at M7 (or earlier if Render auto-deploy).

## Documentation Duties

Code changes that alter behavior/architecture update the matching doc (table in
`.claude/CLAUDE.md`). Non-obvious decisions → ADR. Session end → SESSION.md + TODO.md.
