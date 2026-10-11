# PulseOS — Claude Session Entry Point

> **Read this file first in every session.** It tells you what PulseOS is, where the project
> stands, and where everything else lives. Do not duplicate content from the linked docs here.

## What PulseOS Is

A **patient-centric healthcare interoperability platform** (final-year project, production-grade
ambitions). Every patient gets a permanent **Pulse Health ID** (`PHI-IND-YYYY-XXXXXXC`, ADR-012) usable
across hospitals. Doctors discover that records exist elsewhere but can only open them after the
patient grants **granular, per-category consent**. Every consent/access event is anchored to the
**Polygon Amoy** blockchain. An **AI layer** (OCR → RAG → LLM) produces clinical summaries,
health timelines, a report explainer, and a Health Copilot chat.

- 3 simulated hospitals (TMH Jamshedpur, CMC Vellore, Apollo). No real hospital or ABHA integration in scope.
- Team: ChatGPT (Chief Architect), Claude (Senior Engineer — you), Human (Product Owner / Integrator).
- Human team is 3 students; all code is AI-assisted. Timeline: 7 months (started July 2026).
- Research goal: publishable paper (patient-controlled consent + blockchain audit + RAG summarization). See [docs/PROJECT_OVERVIEW.md](../docs/PROJECT_OVERVIEW.md) §Research.

## Current Status

- **Phase (2026-10-11, Session 017):** M4 substantially done; M5 AI **partially built**;
  **M6.1–M6.3 complete** (local audit integrity; no public chain); M6.4 **not authorized**. `main`
  at `155cbf1`, **38 commits ahead of `origin/main`, none pushed** — pushing is a Product Owner
  action. The working tree also holds uncommitted prerequisite and documentation changes; see
  [SESSION.md](SESSION.md) §Session 017 for the exact state.
- **Completed:** M0.1 scaffold; M0.2 domain design (ADR-011…013); M0.3 walking skeleton (PR #1);
  M2 backend (onboarding per ADR-015, upload → S3 port, presigned downloads, arq worker per
  ADR-014, seed); **M3** (request → per-category decision → grant → revoke, `consent.enforce()`
  on every non-owner record read, append-only audit log, migration 0004, ADR-016…019) — its gate
  criteria are now met in code; **M4 so far** — all three portals built and integrated (patient
  complete, doctor's full consent workflow, hospital portal), hospital audit attribution
  (migration 0005, ADR-022/023/025), authenticated rate limiting (ADR-024), Synthea FHIR R4
  Phase A (10 patients / 889 records), patient record browsing (sort, server-side search,
  category filter, cursor paging), patient audit grouping, patient profile editing
  (`PATCH /patients/me`), and patient record hide/unhide (`PATCH /records/{id}/visibility`).
- **Next:** the **`notifications` module** (access requests still arrive silently — the last M4
  backend item), then **SYSTEM_ADMIN provisioning** (nothing can call `POST /hospitals/{hid}/verify`,
  so a self-registered hospital is stranded `PENDING`), then **QR identity**. A first Playwright
  E2E over the consent journey is the cheapest demo insurance. **Partially built:** M5 AI/RAG —
  `app/modules/ai` exists (ingestion, consent-scoped retrieval, Ollama-only generation, clinical
  assistant, patient copilot) but `workers/tasks.py` still only logs; M6 blockchain per
  **ADR-027** (Merkle-batched v3 anchoring) — the `AuditAnchor` port, network-free
  `LocalChainAuditAnchor`, migration 0006, Keccak-256 v3 digests (M6.1), `consent/merkle.py`
  (M6.2/M6.2.1) and M6.3 (migration 0007 batch/membership tables, deterministic sealing,
  commitments, database-only reconciliation, v3 refused by the per-event workflow) are committed
  in `e3c0fe1` (implementation), with the opt-in PostgreSQL integration tests in `1ce4c14`.
  M6.1–M6.3 are accepted with deferred items. **The M6 gate is not complete. Not built, do not
  describe as working:** on-chain batch submission, receipts, chain-side verification,
  contract, chain adapter, scheduler, reconciliation CLI; M7 hardening/deploy. **M6.4 is not
  authorized.**
- **Health (2026-10-11):** most recent full backend run **1088 passed, 18 skipped** (the 18 skips
  are the opt-in PostgreSQL tests, run only when `PULSEOS_TEST_POSTGRES_URL` is set); those 18
  — batch sealing/classification and migration 0007 — passed against a disposable scratch
  PostgreSQL 16. CI job `backend-postgres` runs them; configured but not yet run on GitHub
  (unpushed). Repo-wide `ruff check` (39), `ruff format --check`
  (20 files) and `mypy` (158 lines, mostly AI tests) report pre-existing findings, so those CI
  steps are not green. Web figures last recorded at session 016 and not re-run since: 463 web
  tests, tsc + eslint + prettier clean, 3/3 builds.
- **Session log / handoff notes:** [SESSION.md](SESSION.md) §Session 017 — read this second, update it before ending every session.
- **Status is owned by [ROADMAP.md](ROADMAP.md)** (milestones, dated validation) and the handoff by
  SESSION.md; the summary above must not grow into a second copy of either.

## Architecture in One Paragraph

A **modular monolith** FastAPI backend (NOT six microservices — see ADR-001) with six internal
modules matching the original service boundaries: `auth`, `patients`, `records`, `consent`, `ai`,
`notifications` (the last is an empty package). PostgreSQL (no pgvector use — retrieval is
lexical, ADR-029), Redis (rate limits + arq queue; the worker only logs today), S3-compatible
object storage (MinIO locally, ADR-005), and a **local Ollama** model for AI generation
(ADR-028). Audit integrity: versioned digests and Merkle batches with an opaque commitment behind
a pluggable anchor port; only hashes would ever go on-chain, and **nothing is submitted yet**
(ADR-004, ADR-027). Frontends: one pnpm/React monorepo with three apps (patient, doctor,
hospital) sharing a UI kit and a typed API client (ADR-003); the Flutter patient app has not
started (ADR-010). Record metadata is **FHIR-aligned** (ADR-006), with Synthea FHIR R4 import
(proposed ADR-030). Full picture: [docs/SYSTEM_ARCHITECTURE.md](../docs/SYSTEM_ARCHITECTURE.md).

## Where Everything Lives

| Need | Read |
|---|---|
| Session state, what happened last time | [.claude/SESSION.md](SESSION.md) |
| Milestones & phase gates | [.claude/ROADMAP.md](ROADMAP.md) |
| Domain glossary, personas, core flows | [.claude/CONTEXT.md](CONTEXT.md) |
| Architecture Decision Records (ADRs) | [.claude/DECISIONS.md](DECISIONS.md) |
| Actionable task list | [.claude/TODO.md](TODO.md) |
| Definition of done, PR/security checklists | [.claude/CHECKLIST.md](CHECKLIST.md) |
| Problem, features, scope, research angle | [docs/PROJECT_OVERVIEW.md](../docs/PROJECT_OVERVIEW.md) |
| System design, module boundaries, data flow | [docs/SYSTEM_ARCHITECTURE.md](../docs/SYSTEM_ARCHITECTURE.md) |
| Chosen technologies + rationale + deltas from original plan | [docs/TECH_STACK.md](../docs/TECH_STACK.md) |
| Repo layout, environments, testing, CI | [docs/DEVELOPMENT_GUIDE.md](../docs/DEVELOPMENT_GUIDE.md) |
| Domain model, RBAC matrix, Health ID design | [docs/DOMAIN_MODEL.md](../docs/DOMAIN_MODEL.md) |
| REST conventions, versioning, errors | [docs/API_GUIDELINES.md](../docs/API_GUIDELINES.md) |
| Data modeling principles + physical table index (migrations/models are authoritative) | [docs/DATABASE_DESIGN.md](../docs/DATABASE_DESIGN.md) |
| AI behaviour as built, and the unbuilt plan | [docs/AI_ARCHITECTURE.md](../docs/AI_ARCHITECTURE.md) |
| Audit integrity, batches, anchoring design | [docs/BLOCKCHAIN_ARCHITECTURE.md](../docs/BLOCKCHAIN_ARCHITECTURE.md) |
| Security controls with implemented/planned status | [docs/SECURITY.md](../docs/SECURITY.md) |
| Git workflow, code style, review rules | [docs/CONTRIBUTING.md](../docs/CONTRIBUTING.md) |

## Engineering Principles (non-negotiable)

1. **Consent is the choke point.** No record content is ever readable without an active consent
   grant checked at a single enforcement layer. Never bypass it "for the demo."
2. **Clean Architecture per module:** router → service (domain logic) → repository (persistence).
   Domain logic never imports FastAPI or SQLAlchemy session details.
3. **Type-safe everywhere:** Python fully type-hinted (mypy strict), TypeScript strict mode, no `any`.
4. **SOLID / DRY / KISS.** Prefer the boring solution. No speculative abstraction; but external
   providers (LLM, storage, blockchain, notifications) always sit behind interfaces.
5. **Secure by default:** deny-by-default authz, presigned short-lived file URLs, no PHI in logs,
   no raw PHI to external LLMs without redaction. See SECURITY.md.
6. **Every schema change via migration (Alembic).** Never mutate the DB by hand.
7. **Tests accompany features** (see CHECKLIST.md); a phase is done only when its gate passes.
8. **Document decisions:** any non-obvious choice gets an ADR in DECISIONS.md.
9. **Update SESSION.md** (and TODO.md) at the end of every working session.

## Hard Rules for Claude Sessions

- Never invent scope. MVP boundary is defined in PROJECT_OVERVIEW.md §Scope.
- Never start the next phase before the current phase gate in ROADMAP.md is met.
- Propose architecture changes as ADR drafts; get Product Owner approval before implementing.
- Demo/seed data must be clearly synthetic — no real patient data, ever.
