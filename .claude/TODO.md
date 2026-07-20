# TODO.md — Actionable Task List

> Keep this short and current. Completed items move to SESSION.md history. 
> Owner codes: FE (frontend lead), BE (backend lead), AI (AI+blockchain lead), PO (product owner), ANY (whoever/Claude).

## Blocked on Product Owner

- [ ] Approve architecture revisions (ADR-001…008) — required before M0 code starts.
- [ ] Decide ADR-009 (deployment: Render vs AWS) — needed by M1 gate.
- [ ] Decide ADR-010 (Flutter timing) — needed by M1 gate.
- [ ] Confirm LLM provider + get API key (Gemini recommended) — needed by M5, key by M0 for experiments.

## M0 — Walking Skeleton (current milestone)

- [ ] BE: Scaffold repo per DEVELOPMENT_GUIDE.md layout (backend/, web/, infra/, .github/).
- [ ] BE: docker-compose with Postgres(+pgvector), Redis, MinIO; `.env.example`.
- [ ] BE: FastAPI skeleton — settings, structured logging, health endpoint, error handler (RFC 7807), Alembic wired.
- [ ] BE: `auth` module — Firebase Auth verification, role claims (patient/doctor/hospital_admin), auth dependency.
- [ ] BE: `patients` module — registration, Health ID issuance (`PHI-IND-2026-XXXXXX`), profile read.
- [ ] FE: pnpm workspace scaffold; patient app shell (login → profile page); shared `api-client` generation from OpenAPI.
- [ ] ANY: GitHub Actions CI — ruff + mypy + pytest (backend), eslint + tsc + vitest (web).
- [ ] ANY: Seed script stub for 3 simulated hospitals.
- [ ] ANY: First commit + push once PO approves foundation.

## M1 — Research & Design (parallel)

- [ ] ALL: Literature review — 3 papers each on HIE consent, blockchain audit, RAG summarization; notes into docs/.
- [ ] FE: Figma — the 3 core journeys (CONTEXT.md) before any other screens.
- [ ] AI: Spike — Gemini free-tier limits vs expected summary/copilot volume; report findings.
- [ ] AI: Spike — EasyOCR vs Tesseract accuracy on 5 synthetic Indian lab-report PDFs.

## Parking Lot (not now)

- Emergency QR security design (break-glass) — Phase 2, needs its own ADR.
- OpenAPI-spec-driven contract tests between web client and backend.
- Synthetic medical record generator for realistic seed/eval data (needed by M5 evals).
