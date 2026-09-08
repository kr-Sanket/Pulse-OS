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

- **Phase:** **M4 — Core Features Complete**, substantially done on `main` (2026-09-08, session
  016). Last feature commit `ea2ebd5`; working tree clean; **20 commits ahead of `origin/main` at
  that commit (21 with the docs commit that follows it), none pushed** — pushing is a Product
  Owner action.
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
  E2E over the consent journey is the cheapest demo insurance. **Not started, do not describe as
  working:** M5 AI/RAG (`workers/tasks.py` still only logs), M6 blockchain (no `AuditAnchor`
  interface exists), M7 hardening/deploy.
- **Health:** **653 backend tests at 97% coverage**, mypy strict + ruff clean; **463 web tests**,
  tsc + eslint + prettier clean; 3/3 web builds; CI green on both.
- **Session log / handoff notes:** [SESSION.md](SESSION.md) §Session 016 — read this second, update it before ending every session.

## Architecture in One Paragraph

A **modular monolith** FastAPI backend (NOT six microservices — see ADR-001) with six internal
modules matching the original service boundaries: `auth`, `patients`, `records`, `consent`, `ai`,
`notifications`. PostgreSQL (+ **pgvector** for embeddings, ADR-002), Redis (queue/cache),
S3-compatible object storage (MinIO locally, ADR-005), async workers for OCR/embedding.
Blockchain is a **pluggable audit-anchor** behind an interface; hashes only go on-chain (ADR-004).
Frontends: one pnpm/React monorepo with three apps (patient, doctor, hospital) sharing a UI kit
and a typed API client (ADR-003), plus a Flutter patient app. Record metadata is **FHIR-aligned**
(ADR-006). Full picture: [docs/SYSTEM_ARCHITECTURE.md](../docs/SYSTEM_ARCHITECTURE.md).

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
| Data modeling principles (conceptual) | [docs/DATABASE_DESIGN.md](../docs/DATABASE_DESIGN.md) |
| OCR/RAG/LLM pipeline design | [docs/AI_ARCHITECTURE.md](../docs/AI_ARCHITECTURE.md) |
| Consent anchoring & smart-contract design | [docs/BLOCKCHAIN_ARCHITECTURE.md](../docs/BLOCKCHAIN_ARCHITECTURE.md) |
| Threat model, authz, data protection | [docs/SECURITY.md](../docs/SECURITY.md) |
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
