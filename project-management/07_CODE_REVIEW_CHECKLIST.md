# PulseOS — Code Review Checklist

> **Document:** `project-management/07_CODE_REVIEW_CHECKLIST.md`
> **Status:** Active — applied by the Lead (and Claude architectural reviews) to every PR before approval
> **Related:** [`06_PR_TEMPLATE.md`](06_PR_TEMPLATE.md) · [`04_DEVELOPMENT_WORKFLOW.md`](04_DEVELOPMENT_WORKFLOW.md) §9–11 · [`docs/CONTRIBUTING.md`](../docs/CONTRIBUTING.md) · [`.claude/CHECKLIST.md`](../.claude/CHECKLIST.md) · [`.claude/DECISIONS.md`](../.claude/DECISIONS.md)

---

## 1. Purpose

This is the official checklist a reviewer walks before approving any PulseOS Pull Request. It exists so approval means the same thing on every PR: the change is in scope, architecturally sound, secure, tested, documented, and safe to squash onto an always-demoable `main`.

Order matters. Sections are arranged by severity: a failure in §3 or §4 blocks the review before style is even read (per `docs/CONTRIBUTING.md`: isolation/consent violations are an instant block).

---

## 2. Review Philosophy

- **Review the contract first, the code second.** The PR is measured against its task assignment (05) and the ADRs — not against what the reviewer would have built.
- **Protect the invariants.** Consent enforcement, deny-by-default authz, append-only audit, module isolation. Everything else is negotiable; these are not.
- **Simplest thing that works.** Extra abstraction is a defect, not a bonus (project principle: prefer the boring solution).
- **Comments cite a reason.** Every request-changes comment names the rule, ADR, or failure scenario behind it. "I'd do it differently" is not a finding.
- **Be hard on code, easy on people.** The committer owns the code — including AI-generated code ("the AI wrote it" is never a review answer, CONTRIBUTING rule 4).
- **A fast, honest "request changes" beats a slow, polite approval.** Review turnaround target: 24 hours.

---

## 3. Architecture Checklist

- [ ] Every touched file is inside the author's ownership (02 §4) — otherwise stop; close the PR
- [ ] Layering intact: router → service → repository; services import no FastAPI/Request objects and construct no HTTP responses (domain exceptions only)
- [ ] Module isolation (ADR-001): no module queries another module's tables; cross-module access only via service interfaces (e.g. `UserAccountService`, `PatientDirectoryService`)
- [ ] No new modules, patterns, or architectural changes without an approved ADR
- [ ] External providers (LLM, storage, blockchain, auth, queue) stay behind their existing ports; no SDK types leak past their adapter file
- [ ] No speculative abstraction; the change is the simplest implementation of the assigned scope
- [ ] Dependency injection via the module's `dependencies.py`; no globals, no service-locator improvisation

## 4. Security Checklist

- [ ] Deny-by-default: every new endpoint declares its role gate; ADR-013 order respected (role → relationship → consent)
- [ ] Record content / metadata-beyond-existence is reachable only through the consent choke point (or, pre-M3, the documented layer-2 relationship seam) — never a new side path
- [ ] 404-not-403 wherever the caller must not learn a resource exists (API_GUIDELINES)
- [ ] Roles/identity from verified claims only — never from request bodies; client-supplied IDs never trusted for ownership
- [ ] SYSTEM_ADMIN appears in no PHI-touching gate (hard invariant, ADR-013)
- [ ] No PHI, tokens, or filenames in logs; errors leak no provider/SDK internals
- [ ] Files only via short-lived presigned URLs issued *after* the authorization check (ADR-005)
- [ ] No secrets in code; new env vars documented in `.env.example` with safe placeholders
- [ ] Nothing goes to an external LLM without the redaction layer (ADR-007; M5+)

## 5. Database Checklist

- [ ] Schema changes are Lead-authored Alembic migrations only — no metadata drift, no manual DDL
- [ ] Migration is reversible; up/down/up covered by the chain test (`test_alembic.py` APP_TABLES extended)
- [ ] Single linear head; revision numbering continues the existing chain (no duplicate revision IDs — this has burned us once)
- [ ] Constraint/index names use the naming convention (`op.f(...)`); enums stored as plain VARCHAR (non-native, no CHECK) per house rule
- [ ] UUID PKs + `created_at`/`updated_at` via mixins; business keys (`PHI-…`, `HID-…`) unique, never FK targets
- [ ] No cross-module ORM relationships — plain FKs only
- [ ] Append-only tables (audit, consent decisions) receive no UPDATE/DELETE paths
- [ ] `alembic/env.py` imports any newly-modeled module

## 6. API Checklist

- [ ] Paths under `/api/v1`; plural kebab-case resources; verb sub-resources for non-CRUD actions
- [ ] camelCase wire fields via `ApiModel`/`RequestModel`; unknown fields rejected on writes (`extra="forbid"`)
- [ ] RFC 7807 problem+json for all errors; correct status usage (401/403/404/409/413/415/422/503) and the 403-vs-404 rule
- [ ] Listings cursor-paginated (`?cursor=&limit=`, max 100, `{items, nextCursor}`) — never offset
- [ ] Idempotency where clients may retry (registrations return 200 on repeat, not 409/duplicate)
- [ ] Long-running work returns `202` + status resource, never blocks the request thread
- [ ] Endpoint docstring states purpose, allowed roles, consent requirement, failure modes
- [ ] OpenAPI contract tests updated for new paths/schemas

## 7. Testing Checklist

- [ ] Every new behavior has tests; every bugfix has a regression test that fails without the fix
- [ ] **Negative authz tests present for every gated surface**: wrong role → 403, out-of-scope resource → 404, unauthenticated → 401
- [ ] Consent/records paths test the enforcement, not just the happy path
- [ ] External services faked (auth, storage, queue, LLM, chain) — no live calls in tests
- [ ] Atomicity verified where claimed (e.g. provider failure → rollback → retry recreates)
- [ ] Coverage holds: ≥80% on `records`/`consent`; no tests deleted/skipped to go green
- [ ] Tests are deterministic (no sleeps, no real network, no wall-clock coupling)

## 8. Documentation Checklist

- [ ] Docs matching the change updated (map in `.claude/CLAUDE.md`); behavior/architecture changes never ship doc-silent
- [ ] Non-obvious decision → ADR added (never edited) by the Lead
- [ ] `CHANGELOG.md` entry for milestone-visible changes; `.env.example` for config changes
- [ ] Comments explain *why* (constraints, domain rules), not *what*; no commented-out code
- [ ] SESSION.md/TODO.md updated when the PR closes a tracked task

## 9. Frontend Checklist

- [ ] All API access through the generated `@pulseos/api-client` — zero direct `fetch()`
- [ ] Only APIs that exist on `main` consumed; no stubbed/imagined endpoints
- [ ] TypeScript strict, no `any` without an inline justification
- [ ] Components used by ≥2 apps live in `packages/ui`; apps never import from each other
- [ ] Error states rendered for every failure mode the API documents (not just the happy path)
- [ ] Protected routes enforce auth; role-inappropriate screens unreachable
- [ ] Responsive + accessible (keyboard, labels, contrast); screenshots attached for UI changes
- [ ] `pnpm build` green for all three portals

## 10. Generated Code Checklist

- [ ] `openapi.json` + `src/generated/schema.ts` changed **only** via `make api-client`, in the same PR as the endpoint change
- [ ] Spec diff reviewed line-by-line and intentional — unintended spec drift = wrong PR (API_GUIDELINES)
- [ ] No hand edits under `web/packages/api-client/src/generated/`
- [ ] Hand-written client surface (`src/index.ts`) changed only by the Lead

## 11. Performance Checklist

- [ ] No N+1 query patterns; joins/single queries where the data is read together
- [ ] No unbounded reads: every list path has a limit; uploads capped before buffering
- [ ] No blocking calls on the event loop (sync SDKs via `asyncio.to_thread`, per the Firebase/boto3 precedent)
- [ ] Expensive artifacts cached/materialized per the architecture (AI summaries M5+), not recomputed per request
- [ ] Indexes exist for new query predicates (FK columns, keyset sort columns)

---

## 12. Common Review Findings

The defects that actually recur in this repository — check for them explicitly:

| Finding | Where it hides |
|---|---|
| Stale-base PR duplicating merged concepts (models, migrations) | Branch point weeks behind `main`; revision-ID collisions |
| Happy-path-only tests on an authz surface | Test file with 201s and no 401/403/404 |
| Business logic drifting into routers | Conditionals beyond error translation in a router function |
| Error translation swallowing distinctions | One domain error for all `IntegrityError`s; dead `if` branches |
| Check-then-insert races | Service pre-checks duplicating what the unique constraint already guards |
| Client-writable privileged fields | Verification/status/role accepted in a request schema |
| PHI in logs "for debugging" | Filenames, names, health IDs in `logger.*` calls |
| Cursor/pagination edge cases untested | No test walking past page one; ties on `created_at` unhandled |
| Generated-file drift | `schema.ts` edited without a matching `openapi.json` diff |
| Scope smuggling | "Also fixed…" in the PR description; files outside the task allowlist |

---

## 13. Review Decision Matrix

| Decision | When | Effect |
|---|---|---|
| **Approve** | All checklists pass; no comments, or nit-only comments the author may take or leave | Lead squash-merges |
| **Approve with comments** | All *blocking* dimensions pass; minor improvements noted (naming, docs polish) that the author addresses in this PR or a logged follow-up | Merge proceeds; follow-ups land in TODO |
| **Request changes** | Any blocking finding: failed checklist item in §3–§11, missing tests, unresolved scope question | Author fixes on the same branch; full re-review of changed areas |
| **Reject (close)** | Scope violation (files outside ownership), duplicate/parallel implementation of an owned concept, PR built on a stale base requiring a restart, or work that contradicts an ADR | PR closed unmerged; work is re-planned as a proper task — salvageable ideas go to the Lead as proposals |

A **Reject** is about the change's premise, not its polish — no amount of fix commits converts a wrong-scope PR into a right one.

---

## 14. Final Review Checklist

The last pass before clicking Approve:

```
☐ Scope matches the task assignment; no smuggled files
☐ §3 Architecture — layering, isolation, ADR compliance
☐ §4 Security — deny-by-default, choke point, no PHI/secrets leakage
☐ §5 Database — Lead-authored, reversible, linear, convention-named
☐ §6 API — guidelines-conformant surface, contract tests updated
☐ §7 Testing — negatives present, coverage holds, all green
☐ §8 Documentation — docs/ADR/CHANGELOG duties met
☐ §9 Frontend — generated client only, states covered, builds green
☐ §10 Generated code — regenerated, intentional, untouched by hand
☐ §11 Performance — bounded, indexed, non-blocking
☐ PR template (06 §4) complete; title is the commit main deserves
☐ CI green on the latest push; every thread resolved with pushed changes
☐ Decision recorded: Approve / Approve w/ comments / Request changes / Reject
```

---

*Maintained by the Lead Developer. This checklist evolves with the codebase — new recurring findings (§12) are added via Lead-approved `docs/*` PRs.*
