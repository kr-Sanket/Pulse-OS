# PulseOS — Claude Session Entry Point

> **Read this file first in every session.** It tells you what PulseOS is, where the project
> stands, and where everything else lives. Do not duplicate content from the linked docs here.

## What PulseOS Is

A **patient-centric healthcare interoperability platform** (final-year project, production-grade
ambitions). Every patient gets a permanent **Pulse Health ID** (`PHI-IND-YYYY-XXXXXXC`, ADR-012) usable
across hospitals. Doctors discover that records exist elsewhere but can only open them after the
patient grants **granular, per-category consent**. Every consent/access event is hashed and can be
sealed into a **local Merkle batch**; anchoring those commitments to **Polygon Amoy** is the design
goal (ADR-004/027) and is **not built**. An **AI layer** answers questions over consented records
(lexical retrieval → local Ollama LLM: clinician assistant and patient Health Copilot); OCR,
automatic summaries, health timelines and a report explainer are planned, not built.

- 3 simulated hospitals (TMH Jamshedpur, CMC Vellore, Apollo). No real hospital or ABHA integration in scope.
- Team: ChatGPT (Chief Architect), Claude (Senior Engineer — you), Human (Product Owner / Integrator).
- Human team is 3 students; all code is AI-assisted. Timeline: 7 months (started July 2026).
- Research goal: publishable paper (patient-controlled consent + blockchain audit + RAG summarization). See [docs/PROJECT_OVERVIEW.md](../docs/PROJECT_OVERVIEW.md) §Research.

## Current Status

- **Phase (2026-10-25, Session 021):** M4 substantially done; M5 AI **partially built**;
  **M6.1–M6.3 complete** (local audit integrity: CLI, API v3 verification/proofs, patient integrity UI;
  no public chain); M6.4 **not authorized**. Preparing for the final review. Session 021's series
  (on top of `0ea4bac`, with the four earlier unpushed commits) is committed and pushed to
  `origin/main`; check GitHub Actions for its CI result (last in-repo record: run #17 on `d09d721`).
  See [SESSION.md](SESSION.md) §Session 021.
- **Completed:** M0–M3 (see ROADMAP); **M4 so far** — all three portals on real APIs, hospital audit
  attribution (ADR-022/023/025), rate limiting (ADR-024), Synthea FHIR R4 import, record browsing with
  keyset pagination, hide/unhide, profile editing, in-app notifications (ADR-031), polling refresh,
  per-category consent decisions (`b08ba2a`), SYSTEM_ADMIN provisioning, directory and dashboard,
  hospital verification with verifier/timestamp (`15e0b1c`, migration 0009), CLI sealing guard
  (`278bbfc`), account-status + token-revocation enforcement (`65b68fe`), consent-gated **FHIR R4
  export** (`2e05ee4`), **audit API v3** verification/proofs/batches (`c7e5359`), consent
  revalidation after AI retrieval/synthesis and export reads (`0ea4bac`). Session 021:
  VERIFIED now requires Merkle inclusion on every surface, proof endpoint no longer 500s on tampered
  membership, AI denials/discards audited as `ACCESS_DENIED`, `audit_batch_verify` rate limit,
  patient FHIR export button, audit integrity badge + proof dialog, suspended-account routing,
  regenerated OpenAPI/client (42 operations under `/api/v1`), CI build + client-drift steps.
- **Next — final review priorities** ([ROADMAP.md](ROADMAP.md), [TODO.md](TODO.md) §0a): (1) authz/audit
  correctness ✅; (2) per-category consent UI ✅; (3) SYSTEM_ADMIN + hospital verification 🟡 (rejection
  lifecycle and verification audit event open — policy needed); (4) demonstrable local audit integrity ✅
  for the review (scheduler open); (5) FHIR R4 export ✅ patient UI, API for clinicians (not HL7-validated).
  QR identity open. **There is no E2E suite and none is to be rebuilt** (removed in `281439c`).
  **Not built, do not describe as working:** upload indexing/OCR (`workers/tasks.py` only logs),
  embeddings, on-chain submission, receipts, contract, chain adapter, sealing scheduler, append-only DB
  triggers; M7 hardening/deploy. **M6.4 is not authorized.**
- **Health (2026-10-25, local only — not CI):** backend **1351 passed, 26 skipped** (opt-in PostgreSQL
  tests not run); ruff format/lint and strict `mypy` clean (173 files). Web **689 passed** across 5 tested
  packages; prettier, eslint, tsc clean; `pnpm build` succeeds.
- **Session log / handoff notes:** [SESSION.md](SESSION.md) §Session 021 — read this second, update it before ending every session.
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
via CLI (proposed ADR-030) and a consent-gated FHIR R4-shaped Bundle export (not HL7-validated). Full picture: [docs/SYSTEM_ARCHITECTURE.md](../docs/SYSTEM_ARCHITECTURE.md).

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
