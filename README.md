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

**M0, M2 and M3 backends complete. M4 in progress: the patient portal is fully integrated and
the doctor portal's first slice is live.**

The backend exposes 25 operations under `/api/v1`: Firebase-backed auth with PulseOS role claims,
patient registration and Health ID issuance (ADR-012), hospital/doctor onboarding (ADR-015),
record upload → S3/MinIO with FHIR-aligned metadata and presigned downloads, and the consent
domain — access request → per-category approve/reject → grant → revoke, with a single
enforcement choke point in front of every non-owner record read and an append-only, hashed audit
log behind it (ADR-016…019). M4 added the patient-facing read side: `GET /consent-grants`,
`GET /audit-logs`, a batched staff identity projection so patients see names rather than UUIDs,
and `GET /records/existence` — the clinician discovery step, which returns record *categories*
and nothing else.

The **patient portal** (7 pages) runs entirely on real APIs. The **doctor portal** covers login →
dashboard → patient search by Health ID → available categories; the request-access flow is next
and is the last thing standing between the repository and an end-to-end consent demo. The
**hospital portal** is still a scaffold, and the AI and blockchain layers have not started.

320 backend tests at 97% coverage; 131 web tests. See [`.claude/SESSION.md`](.claude/SESSION.md)
for the current-state handoff, [`.claude/TODO.md`](.claude/TODO.md) for remaining work, and
[`.claude/ROADMAP.md`](.claude/ROADMAP.md) for the milestone plan.

## Stack (summary)

FastAPI modular monolith · PostgreSQL + pgvector · Redis workers · S3/MinIO · Firebase Auth ·
React + TypeScript monorepo (3 portals) · Flutter (patient app) · LangChain + Ollama ·
Solidity on Polygon Amoy (hash-only consent anchoring) · Docker · GitHub Actions.
Details and rationale: [`docs/TECH_STACK.md`](docs/TECH_STACK.md).
