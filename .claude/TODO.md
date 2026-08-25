# TODO.md — Actionable Task List

> Keep this short and current. Completed items move to SESSION.md history. 
> Owner codes: FE (frontend lead), BE (backend lead), AI (AI+blockchain lead), PO (product owner), ANY (whoever/Claude).

## Blocked on Product Owner

- [ ] Approve M0.2 domain design: docs/DOMAIN_MODEL.md + ADR-011/012/013 — required before M0.3 code.
- [ ] Decide OD-1 (unclaimed patients: recommend NO for MVP), OD-2 (grant expiry: recommend 90d adjustable), OD-3 (grant exposes health profile: recommend YES, explicit on consent screen) — see DOMAIN_MODEL.md §5.
- [ ] Push to GitHub and verify CI runs green (local commits made in session 006 per PO's
      implementation-start directive; push awaiting explicit go-ahead).
- [ ] Resolve Review-1 deck conflict: Spring Boot + Synthea (slide 20) vs ADR-001 FastAPI +
      3-simulated-hospitals plan — amend ADRs or fix the slide (see SESSION.md session 005).
- [ ] Decide ADR-009 (deployment: Render vs AWS) — needed by M1 gate.
- [ ] Decide ADR-010 (Flutter timing) — needed by M1 gate.
- [ ] Confirm LLM provider + get API key (Gemini recommended per ADR-007) — needed by M5, key earlier for experiments.

## M0.1 — Scaffold ✅ DONE (2026-07-20, session 002)

- [x] Repo scaffold per DEVELOPMENT_GUIDE.md layout (backend/, web/, mobile/, contracts/, infra/, scripts/, .github/).
- [x] docker-compose with Postgres(+pgvector), Redis, MinIO + bucket bootstrap; `.env.example`; Makefile; `.editorconfig`.
- [x] FastAPI skeleton — settings, health endpoint, module packages; ruff/mypy/pytest green.
- [x] pnpm workspace — 3 portal shells + config/ui/api-client packages; prettier/eslint/tsc/vitest green.
- [x] GitHub Actions CI — backend + web jobs (untested on GitHub until first push).

## M0.2 — Domain Design ✅ DONE (2026-07-20, session 003 — see DOMAIN_MODEL.md)

## M0.3 — Walking Skeleton (next, after PO approval of M0.2)

- [x] ANY: First commit of scaffold + docs (session 006). Push + GitHub CI verification still pending (see Blocked on PO).
- [ ] ANY: Verify `make up` against a real Docker daemon (Docker still not installed on dev machine as of session 006, 2026-08-25).
- [x] BE: Alembic wiring (async env.py, Settings-driven URL, reversible-migration template) — session 008. First migration lands with the first models (auth/patients).
- [x] BE: Structured logging + RFC 7807 error handler + request-id middleware + /ready probe — session 008.
- [x] BE: `auth` module — Firebase Auth port + verification dependency, role claims
      (`pulseos_role`/`pulseos_user_id`), role gates per ADR-013 layer 1 — session 009.
      Claim *provisioning* happens at registration (patients module, Part 3).
- [ ] BE: `patients` module — registration, Health ID issuance (`PHI-IND-2026-XXXXXX`), profile read.
- [ ] FE: patient app login → profile page; `api-client` generation from OpenAPI (script in scripts/).
- [ ] ANY: Seed script stub for 3 simulated hospitals.

## M1 — Research & Design (parallel)

- [ ] ALL: Literature review — 3 papers each on HIE consent, blockchain audit, RAG summarization; notes into docs/.
- [ ] FE: Figma — the 3 core journeys (CONTEXT.md) before any other screens.
- [ ] AI: Spike — Gemini free-tier limits vs expected summary/copilot volume; report findings.
- [ ] AI: Spike — EasyOCR vs Tesseract accuracy on 5 synthetic Indian lab-report PDFs.

## Parking Lot (not now)

- Emergency QR security design (break-glass) — Phase 2, needs its own ADR.
- OpenAPI-spec-driven contract tests between web client and backend.
- Synthetic medical record generator for realistic seed/eval data (needed by M5 evals).
