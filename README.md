# PulseOS

**A Patient-Centric Healthcare Interoperability Platform** — Universal Health Identity,
patient-controlled granular consent, blockchain-anchored audit trails, and AI-powered medical
intelligence. Final-year project, 2026, team of 3. Built to production standards with a research
publication goal.

*One Patient. One Identity. One Health History. Accessible Anywhere.*

## Start Here

| Reader | Entry point |
|---|---|
| AI engineering sessions (Claude) | [`.claude/CLAUDE.md`](.claude/CLAUDE.md) |
| Humans, first read | [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) |
| System design | [`docs/SYSTEM_ARCHITECTURE.md`](docs/SYSTEM_ARCHITECTURE.md) |
| Contributing & workflow | [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) |
| Milestones | [`.claude/ROADMAP.md`](.claude/ROADMAP.md) |

## Status

**Phase 0 — Foundation & Planning.** Architecture review complete; documentation foundation in
place; no application code yet. Next milestone: **M0 — Walking Skeleton**.

## Stack (summary)

FastAPI modular monolith · PostgreSQL + pgvector · Redis workers · S3/MinIO · Firebase Auth ·
React + TypeScript monorepo (3 portals) · Flutter (patient app) · LangChain + Gemini ·
Solidity on Polygon Amoy (hash-only consent anchoring) · Docker · GitHub Actions.
Details and rationale: [`docs/TECH_STACK.md`](docs/TECH_STACK.md).

> All patient data in this project is synthetic. PulseOS is a research prototype, not a medical
> device, and provides no medical advice.
