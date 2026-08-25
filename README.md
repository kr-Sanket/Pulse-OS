# PulseOS

**A Patient-Centric Healthcare Interoperability Platform** — Universal Health Identity,
patient-controlled granular consent, blockchain-anchored audit trails, and AI-powered medical
intelligence. Final-year project, 2026, team of 3. Built to production standards with a research
publication goal.

*One Patient. One Identity. One Health History. Accessible Anywhere.*

> All patient data in this project is synthetic. PulseOS is a research prototype, not a medical
> device, and provides no medical advice.

## Repository Map

| Path | What it is |
|---|---|
| `backend/` | FastAPI modular monolith (Python 3.12+) |
| `web/` | pnpm monorepo: patient / doctor / hospital portals + shared packages |
| `mobile/` | Flutter patient app (starts later — ADR-010) |
| `contracts/` | Solidity consent-anchor contract (starts M6) |
| `infra/` | docker-compose for local infrastructure |
| `scripts/` | Seed, codegen, reconciliation scripts |
| `docs/` | Architecture & process documentation — start with [`PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) |
| `.claude/` | AI session memory — entry point [`CLAUDE.md`](.claude/CLAUDE.md) |

## Quickstart

**Prerequisites:** Docker Desktop, Python ≥ 3.12, Node ≥ 20 with pnpm
(`corepack enable` gives you pnpm), `make`.

```bash
# 1. Clone and enter
git clone <repo-url> pulse-os && cd pulse-os

# 2. Create your .env (safe local defaults; no edits needed for local dev)
make env

# 3. Start infrastructure: PostgreSQL+pgvector, Redis, MinIO (+ bucket bootstrap)
make up

# 4. Install dependencies (backend venv + web workspace)
make install

# 5. Run the backend  →  http://localhost:8000  (health: /health, docs: /docs)
make dev-api

# 6. Run a portal (separate terminal)
make dev-patient    # http://localhost:5173
make dev-doctor     # http://localhost:5174
make dev-hospital   # http://localhost:5175
```

**Quality checks** (same as CI): `make lint`, `make typecheck`, `make test` — or all at once,
`make ci`. Auto-format with `make format`. Stop infrastructure with `make down` (data persists
in named volumes).

**MinIO console:** http://localhost:9001 (credentials in your `.env`).

## Contributing

Workflow, branch naming, and review rules: [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md).
Every PR must satisfy [`.claude/CHECKLIST.md`](.claude/CHECKLIST.md). Milestones and phase
gates: [`.claude/ROADMAP.md`](.claude/ROADMAP.md).

## Status

**Phase 0 — M0.1 engineering scaffold and M0.2 domain design complete.** No business features
yet. Next: M0.3 (walking skeleton: auth, Health ID issuance, patient profile end-to-end) —
see [`.claude/ROADMAP.md`](.claude/ROADMAP.md) and [`docs/DOMAIN_MODEL.md`](docs/DOMAIN_MODEL.md).

## Stack (summary)

FastAPI modular monolith · PostgreSQL + pgvector · Redis workers · S3/MinIO · Firebase Auth ·
React + TypeScript monorepo (3 portals) · Flutter (patient app) · LangChain + Gemini ·
Solidity on Polygon Amoy (hash-only consent anchoring) · Docker · GitHub Actions.
Details and rationale: [`docs/TECH_STACK.md`](docs/TECH_STACK.md).
