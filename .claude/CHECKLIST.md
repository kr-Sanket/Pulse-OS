# CHECKLIST.md — Quality Gates

## Definition of Done (every feature)

- [ ] Type-checks clean (mypy strict / tsc strict). No `Any`/`any` escapes without a comment explaining why.
- [ ] Unit tests for domain logic; integration test for the happy path + one failure path.
- [ ] Authz verified: tested that the *wrong* role/patient gets 403/404 — not just that the right one succeeds.
- [ ] If it touches records or consent: consent enforcement path covered by a test.
- [ ] No PHI or secrets in logs (check log statements you added).
- [ ] DB changes via Alembic migration, reversible.
- [ ] OpenAPI spec still generates a valid client (`api-client` regenerated if endpoints changed).
- [ ] Docs updated if behavior/architecture changed (which doc? see CLAUDE.md table). ADR written if the decision was non-obvious.
- [ ] SESSION.md + TODO.md updated at session end.

## Pull Request Checklist

- [ ] One logical change per PR; title follows Conventional Commits (see CONTRIBUTING.md).
- [ ] CI green (lint, typecheck, tests).
- [ ] Reviewed by at least one other member (or Claude review noted in PR description).
- [ ] No commented-out code, no leftover debug prints, no TODOs without a TODO.md entry.

## Security Checklist (any PR touching auth, consent, records, or files)

- [ ] Endpoint denies by default — explicit role + ownership/consent check.
- [ ] File access only via short-lived presigned URL issued *after* consent check.
- [ ] Audit log entry written for every record read/download (append-only, in the same transaction as authorization where applicable).
- [ ] Input validated at the boundary (Pydantic/zod); IDs never trusted from the client for ownership.
- [ ] Nothing sent to an external LLM without passing the redaction layer.
- [ ] No new secrets in code — env vars only, `.env.example` updated.

## Phase-Gate Checklist (before declaring a milestone done)

- [ ] Every gate criterion in ROADMAP.md demonstrably passes (run the demo flow, don't assume).
- [ ] Coverage on the milestone's core module ≥ 80%.
- [ ] `docker compose up` from a clean checkout works — verified by a member who didn't build the feature.
- [ ] SESSION.md milestone entry written; ROADMAP.md status updated; PO sign-off recorded.
