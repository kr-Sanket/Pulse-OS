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

- **Phase (2026-10-17, Session 020):** M4 substantially done; M5 AI **partially built**;
  **M6.1–M6.3 complete** (local audit integrity; CLI sealing/verification; no public chain); M6.4 **not authorized**.
  Preparing for the final review. `main` at `d09d721`, **level with `origin/main` (pushed)**.
  GitHub Actions workflow is reported **GREEN** (workflow run #17, user-provided evidence). See [SESSION.md](SESSION.md) §Session 020.
- **Completed:** M0.1 scaffold; M0.2 domain design (ADR-011…013); M0.3 walking skeleton (PR #1);
  M2 backend (onboarding per ADR-015, upload → S3 port, presigned downloads, arq worker per
  ADR-014, seed); **M3** (request → per-category decision → grant → revoke, `consent.enforce()`
  on every non-owner record read, append-only audit log, migration 0004, ADR-016…019) — its gate
  criteria are now met in code; **M4 so far** — all three portals built and integrated (patient
  complete, doctor's full consent workflow, hospital portal), hospital audit attribution
  (migration 0005, ADR-022/023/025), authenticated rate limiting (ADR-024), Synthea FHIR R4
  Phase A (10 patients / 889 records), patient record browsing (sort, server-side search,
  category filter, composite keyset cursor pagination), patient audit grouping, patient profile editing
  (`PATCH /patients/me`), patient record hide/unhide (`PATCH /records/{id}/visibility`),
  **in-app notifications** (ADR-031, migration 0008, `15b2d1b`), automatic consent/permission
  refresh by polling (`5690a93`), granted-category indicators in the doctor portal (`13e2034`),
  **authorization and audit correctness** (`a09d41f`, `7c27aa0`), **granular per-category consent decisions**
  and recovery (`b08ba2a`), **local SYSTEM_ADMIN provisioning** (`b045f10`), **hospital directory API**
  (`98f3b33`, 39 operations under `/api/v1`), **dedicated System Admin dashboard** (`96a2191`),
  **hospital token-refresh recovery** (`e48017a`), **medical record keyset pagination stabilization** (`d09d721`),
  and **audit-integrity CLI workflow** (`e350b2a`).
- **Next — final review priorities** ([ROADMAP.md](ROADMAP.md) §Final review priorities,
  [TODO.md](TODO.md) §0a): (1) authorization and audit correctness — ✅ **done** (`a09d41f`); (2) per-category
  consent decisions in the patient UI — ✅ **done** (`b08ba2a`); (3) SYSTEM_ADMIN provisioning + hospital
  verification — 🟡 **partially implemented** (`b045f10`, `98f3b33`, `96a2191`, `e48017a`; verifier/timestamp recording and
  rejection lifecycle open); (4) demonstrable local audit integrity — 🟡 **CLI done** (`e350b2a`; scheduler,
  missing CLI safety guard, API v3 Merkle verification, and UI open); (5) FHIR R4 export — ⬜ **not started**. QR identity is still
  open. **There is no E2E suite and none is to be rebuilt** (removed in `281439c`).
  **Partially built:** M5 AI/RAG — `app/modules/ai` exists (FHIR ingestion, consent-scoped
  substring-lexical retrieval, Ollama/Qwen3:8B-only generation, clinical assistant, patient
  copilot) but `workers/tasks.py` still only logs, so uploads are never indexed; M6 blockchain per
  **ADR-027** (Merkle-batched v3 anchoring) — the `AuditAnchor` port, network-free
  `LocalChainAuditAnchor`, migration 0006, Keccak-256 v3 digests (M6.1), `consent/merkle.py`
  (M6.2/M6.2.1), M6.3 batch persistence, and `scripts/audit_integrity.py` CLI workflow (`e350b2a`).
  M6.1–M6.3 are accepted with deferred items. **The M6 gate is not complete. Not built, do not
  describe as working:** on-chain batch submission, receipts, chain-side verification,
  contract, chain adapter, scheduler, patient verification API/UI; M7 hardening/deploy. **M6.4 is not
  authorized.**
- **Health (2026-10-17, commit `d09d721`, verified local & GitHub Actions CI reported green via user-provided evidence):** backend **1209 passed,
  25 skipped** (the 25 skips are the opt-in PostgreSQL tests; the PostgreSQL CI job was reported passed in GitHub Actions run #17, user-provided evidence);
  ruff format/lint and `mypy` clean (166 source files). Web: **611 tests passed** across 6 packages, prettier +
  eslint + tsc clean. GitHub Actions is reported green across all jobs (workflow run #17, user-provided evidence).
- **Session log / handoff notes:** [SESSION.md](SESSION.md) §Session 020 — read this second, update it before ending every session.
- **Status is owned by [ROADMAP.md](ROADMAP.md)** (milestones, dated validation) and the handoff by
  SESSION.md; the summary above must not grow into a second copy of either.

## Architecture in One Paragraph

A **modular monolith** FastAPI backend (NOT six microservices — see ADR-001) with six internal
modules matching the original service boundaries: `auth`, `patients`, `records`, `consent`, `ai`,
`notifications` (in-app only, ADR-031). PostgreSQL (no pgvector use — retrieval is
lexical, ADR-029; host port 5433 → container 5432), Redis (rate limits + arq queue; the worker
only logs today), S3-compatible
object storage (MinIO locally, ADR-005), and a **local Ollama** model for AI generation
(ADR-028). Audit integrity: versioned digests and Merkle batches with an opaque commitment behind
a pluggable anchor port; only hashes would ever go on-chain, and **nothing is submitted yet**
(ADR-004, ADR-027). Frontends: one pnpm/React monorepo with three apps (patient, doctor,
hospital) sharing a UI kit and a typed API client (ADR-003); the Flutter patient app has not
started (ADR-010). Record metadata is **FHIR-aligned** (ADR-006), with Synthea FHIR R4 import
via CLI (proposed ADR-030); there is no FHIR export. Full picture: [docs/SYSTEM_ARCHITECTURE.md](../docs/SYSTEM_ARCHITECTURE.md).

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
