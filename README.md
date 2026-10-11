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
| `contracts/` | Placeholder for a future commitment-registry contract (toolchain undecided; nothing built) |
| `infra/` | docker-compose for local infrastructure (PostgreSQL, Redis, MinIO) |
| `scripts/` | Seed, Synthea import, AI backfill, OpenAPI client codegen |
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

# 3. Start infrastructure: PostgreSQL (pgvector image; extension unused), Redis, MinIO (+ bucket bootstrap)
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

**Database and AI:** apply migrations and seed before first use, and run a local Ollama for the
AI endpoints (or set `PULSEOS_AI_PROVIDER=fake`) — see
[`docs/DEVELOPMENT_GUIDE.md`](docs/DEVELOPMENT_GUIDE.md).

## Contributing

Workflow, branch naming, and review rules: [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md).
Every PR must satisfy [`.claude/CHECKLIST.md`](.claude/CHECKLIST.md). Milestones and phase
gates: [`.claude/ROADMAP.md`](.claude/ROADMAP.md).

## Status

Detailed, dated status and validation evidence live in [`.claude/ROADMAP.md`](.claude/ROADMAP.md);
this is a summary as of 2026-10-11.

- **Complete:** M0 foundation, M2 backend core, M3 consent domain (gate criteria met in code),
  and audit-integrity stages **M6.1–M6.3** — versioned Keccak-256 audit hashing, Merkle batch
  sealing with commitments, and database-only reconciliation.
- **Substantially done (M4):** patient, doctor and hospital portals on real APIs, including the
  full consent journey. Still open: notifications, QR identity, SYSTEM_ADMIN provisioning,
  hospital bulk upload.
- **Partially built (M5 AI):** FHIR-based ingestion, consent-scoped lexical retrieval, a
  clinician AI assistant and a patient Health Copilot using a local Ollama model. OCR, summaries,
  timeline and report explainer are not built.
- **Not built:** any public-chain submission (no contract, adapter, wallet or receipts) — **M6.4
  is not authorized** — and M7 hardening/deployment.

The backend exposes 34 operations under `/api/v1` plus `/health` and `/ready` (the generated
OpenAPI is authoritative). Latest local backend run (2026-10-11): **1088 passed, 18 skipped**; the
18 opt-in PostgreSQL tests passed separately against a disposable PostgreSQL 16 database. GitHub
Actions has not run on these commits yet (not pushed). See [`.claude/SESSION.md`](.claude/SESSION.md)
for the current handoff and [`.claude/TODO.md`](.claude/TODO.md) for remaining work.

## Stack (summary)

FastAPI modular monolith · PostgreSQL · Redis (rate limits, arq) · S3/MinIO · Firebase Auth ·
React 19 + TypeScript monorepo (3 portals) · local Ollama (Qwen3:8B) with lexical retrieval ·
Keccak-256 / Merkle audit batches (public-chain anchoring planned, not built) · Docker Compose ·
GitHub Actions. Flutter patient app not started.
Details and rationale: [`docs/TECH_STACK.md`](docs/TECH_STACK.md).
