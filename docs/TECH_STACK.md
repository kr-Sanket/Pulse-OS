# Technology Stack

> Stack as **used by the code** (verified 2026-10-11 against `backend/pyproject.toml`,
> `web/*/package.json` and `infra/docker-compose.yml`), followed by what is planned or undecided.
> Column "Δ" records changes from the original plan; rationale in `.claude/DECISIONS.md`.

## In use

### Backend

| Technology | Used for | Δ vs original plan |
|---|---|---|
| Python ≥ 3.12 (CI: 3.12) + FastAPI | Modular-monolith API | Was: 6 microservices + gateway → **ADR-001** |
| Pydantic v2 + pydantic-settings | Settings, request/response validation | — |
| SQLAlchemy 2 (async) + asyncpg + Alembic | ORM, PostgreSQL driver, versioned migrations | Migrations were unspecified; now mandatory |
| PostgreSQL 16 | Metadata, consent, audit, audit batches, AI documents/chunks | Image is `pgvector/pgvector:pg16`, but **pgvector is not used** (ADR-029) |
| Redis | Rate limiting (ADR-024), arq job queue | New → **ADR-008** |
| arq | Async worker (only a logging `record_uploaded` task today) | Chosen over Celery → **ADR-014** |
| Firebase Admin SDK | ID-token verification, custom-claim roles | **ADR-011** |
| boto3 against S3 API (MinIO locally) | File storage, presigned URLs | Was: "S3 / Cloudinary" → **ADR-005** |
| httpx | HTTP client (Ollama provider) | — |
| pycryptodome | Ethereum Keccak-256 for v3 audit digests and Merkle commitments | New → **ADR-019** resolution, **ADR-027** |

### AI

| Technology | Used for | Δ |
|---|---|---|
| Ollama, model Qwen3:8B (local) | Answer generation for the clinical assistant and patient copilot, behind the `AnswerGenerator` protocol | Replaces Gemini → **ADR-028** (supersedes ADR-007 in part) |
| Deterministic lexical retrieval (in-house) | Consent-scoped chunk retrieval with clinical synonyms | Replaces pgvector + LangChain for now → **ADR-029** |

### Frontend

| Technology | Used for | Δ |
|---|---|---|
| React 19 + TypeScript (strict) + Vite | Patient / Doctor / Hospital portals | Was: 3 separate apps → **ADR-003**: one pnpm monorepo, shared packages |
| Tailwind CSS | Styling + shared design tokens | — |
| Generated OpenAPI client (openapi-typescript) | Type-safe API access shared by all portals | New → **ADR-003** |

### Infrastructure and tooling

| Technology | Used for | Δ |
|---|---|---|
| Docker Compose | Local infrastructure only: PostgreSQL, Redis, MinIO, bucket bootstrap | API and worker run on the host (`make dev-api`), not in Compose |
| GitHub Actions | CI: backend lint/typecheck/tests, web checks; an opt-in PostgreSQL integration job (see DEVELOPMENT_GUIDE.md) | — |
| ruff + mypy (strict) / eslint + prettier + tsc | Lint, format, static analysis | Enforced in CI (see DEVELOPMENT_GUIDE.md for current status) |

## Planned or undecided (not in the code)

| Technology | Intended use | Status |
|---|---|---|
| Solidity commitment registry + toolchain (Hardhat or Foundry) | On-chain batch-commitment registry | **Undecided**; no contract exists; M6.4+ not authorized |
| Polygon Amoy testnet | Publishing batch commitments (hash only) | **Not implemented** (ADR-004 as amended, ADR-027) |
| web3 client library | Backend → chain submission | **Not chosen, not a dependency** |
| EasyOCR / Tesseract | OCR of uploaded documents | **Not implemented** (original plan) |
| pgvector + LangChain | Embedding retrieval | **Deferred** (ADR-029) |
| Firebase Cloud Messaging | Push notifications | **Not planned** — notifications are in-app only, polled by the portals (ADR-031) |
| Playwright / Cypress | End-to-end browser tests | **Not used** — E2E infrastructure removed (`281439c`); not planned for the final review |
| Flutter | Patient mobile app | **Not started**; timing pending **ADR-010** |
| Render or AWS | Hosting | Pending **ADR-009** |
| Sentry | Error tracking | **Not implemented** (placeholder variable only) |

## Explicitly not used (and why)

- **FAISS** — replaced in the plan by pgvector (ADR-002), itself now deferred (ADR-029).
- **Gemini / external LLM APIs** — removed; local Ollama only (ADR-028).
- **Cloudinary** — media CDN, wrong tool for confidential documents (ADR-005).
- **Kubernetes / service mesh / message brokers (Kafka etc.)** — ops cost without benefit at this
  scale (ADR-001).
- **Hyperledger** — rejected in the original plan.
- **A real FHIR server (HAPI etc.)** — we align to FHIR shapes (ADR-006) and import FHIR R4
  bundles (proposed ADR-030) without running one. FHIR export is not built.
