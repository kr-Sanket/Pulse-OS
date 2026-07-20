# Technology Stack

> Final stack after architecture review. Column "Δ" marks changes from the original plan
> (rationale in the linked ADRs — `.claude/DECISIONS.md`).

## Backend

| Technology | Used for | Δ vs original plan |
|---|---|---|
| Python 3.12 + FastAPI | Modular-monolith API (also acts as gateway) | Was: 6 microservices + gateway → **ADR-001** |
| Pydantic v2 | Settings, request/response validation | — |
| SQLAlchemy 2 + Alembic | ORM + versioned migrations | Migrations were unspecified; now mandatory |
| PostgreSQL 16 + **pgvector** | Metadata, consent, audit, **and vectors** | Was: FAISS for vectors → **ADR-002** |
| Redis | Job queue, cache, rate limiting | New — no async story existed → **ADR-008** |
| arq (or Celery, decide at M2) | Async workers: OCR, embeddings, LLM, anchoring, notifications | New → **ADR-008** |
| Firebase Auth | Phone OTP, Google login, token issuance; roles via custom claims | — |
| S3 API (MinIO local / S3 prod) | Encrypted file storage, presigned URLs | Was: "S3 / Cloudinary" → **ADR-005** |

## AI

| Technology | Used for | Δ |
|---|---|---|
| EasyOCR (Tesseract fallback) | Text extraction from PDFs/scans | Spike at M1 to confirm accuracy |
| LangChain | RAG pipeline orchestration | Retriever = pgvector, not FAISS |
| Gemini API (primary) | Summaries, explainer, copilot, timeline extraction, embeddings | Was "Gemini / OpenAI" → **ADR-007**: one primary behind `LLMProvider` interface |
| Internal redaction layer | Strip identifiers before any external LLM call | New — **ADR-007** / SECURITY.md |

## Blockchain

| Technology | Used for | Δ |
|---|---|---|
| Solidity + Hardhat | Consent/audit anchor contract | — |
| Polygon Amoy testnet | Anchoring (hash-only) | Was "consent recorded on blockchain" → **ADR-004**: DB authoritative, chain = tamper-evidence, async + non-blocking |
| web3.py | Backend → chain writes (from worker) | — |

## Frontend

| Technology | Used for | Δ |
|---|---|---|
| React 18 + TypeScript (strict) + Vite | Patient / Doctor / Hospital portals | Was: 3 separate apps → **ADR-003**: one pnpm monorepo, shared packages |
| Tailwind CSS | Styling + shared design tokens | — |
| Generated OpenAPI client | Type-safe API access shared by all portals | New → **ADR-003** |
| Flutter | Patient mobile app | Timing pending **ADR-010** |
| Firebase Cloud Messaging | Push notifications | Made explicit (was vague) |

## Infrastructure

| Technology | Used for | Δ |
|---|---|---|
| Docker + docker-compose | Local dev parity (api, worker, pg, redis, minio) | — |
| GitHub Actions | CI: lint, typecheck, test on every PR | — |
| Render (recommended) or AWS | Hosting api/worker/Postgres/Redis | Pending **ADR-009** |
| Sentry (free tier) | Error tracking | New |
| ruff + mypy / eslint + prettier | Lint & static analysis | New — enforced in CI |

## Explicitly Not Used (and why)

- **FAISS** — replaced by pgvector (ADR-002: persistence, consent-scoped filtering in SQL).
- **Cloudinary** — media CDN, wrong tool for confidential documents (ADR-005).
- **Kubernetes / service mesh / message brokers (Kafka etc.)** — massive ops cost, zero benefit at this scale (ADR-001).
- **Hyperledger** — original plan already rejected it; Polygon Amoy confirmed.
- **A real FHIR server (HAPI etc.)** — we align to FHIR shapes (ADR-006) without running one.
