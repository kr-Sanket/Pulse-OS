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

- **Phase:** M3 Consent Domain — **backend COMPLETE** (2026-09-01, session 014, branch `feature/consent`, largely uncommitted); M0 and the M2 backend fully done.
- **Completed:** M0.1 scaffold; M0.2 domain design (ADR-011…013); M0.3 walking skeleton (auth, Health ID, patient registration/profile, patient web portal, api-client, seed — merged as PR #1); M2 backend (hospital/doctor onboarding per ADR-015, record upload → S3 port, presigned downloads, arq worker per ADR-014, demo-actor seed); M3 backend (consent request → per-category decision → grant → revoke, `consent.enforce()` on every non-owner record read, append-only audit log, migration 0004, records ⇄ consent integration — ADR-016…019).
- **Next milestone:** M3 frontend (doctor search + request flow, patient consent inbox and audit view) plus the two backend pieces those journeys need — the clinician-facing record-existence projection and a patient audit-log endpoint — both now listed under M4. The M3 gate is **not yet demonstrable end to end**: the backend passes every criterion in `tests/test_m3_gate.py`, but there is no UI. Deferred M3 review findings and the still-open PO items (ops/Docker, OD-1…3, ADR-009/010) are in TODO.md.
- **Session log / handoff notes:** [SESSION.md](SESSION.md) — read this second, update it before ending every session.

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
