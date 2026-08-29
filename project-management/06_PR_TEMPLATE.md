# PulseOS — Pull Request Template

> **Document:** `project-management/06_PR_TEMPLATE.md`
> **Status:** Active — every PR uses the template in §4
> **Related:** [`04_DEVELOPMENT_WORKFLOW.md`](04_DEVELOPMENT_WORKFLOW.md) §8–12 · [`05_TASK_ASSIGNMENT_TEMPLATE.md`](05_TASK_ASSIGNMENT_TEMPLATE.md) · [`03_BRANCH_STRATEGY.md`](03_BRANCH_STRATEGY.md) §11 · [`.claude/CHECKLIST.md`](../.claude/CHECKLIST.md)

---

## 1. Purpose

The PR description is the reviewer's map and the project's permanent record of *why* a change happened. A complete PR description:

- lets the Lead review against the **task assignment**, not against guesswork;
- makes the squash commit on `main` traceable to a task, a milestone, and a decision trail;
- forces the author to self-review — half of all defects are caught while filling in the template;
- protects reviewers' time: a PR that answers the standard questions up front is reviewed in one pass.

An empty or partial description is grounds to return the PR without review.

---

## 2. PR Workflow

Defined in SOP §8–§12; summarized:

```
Local gates green (make ci)
      ↓
Open PR — template §4 filled, title = Conventional Commit
      ↓
Self-check against §3 (author)
      ↓
Request review → Lead review + Claude architectural review (substantive changes)
      ↓
Address comments → push fixes → re-request review
      ↓
Lead approval
      ↓
Squash merge by Lead (PR title becomes the commit on main)
      ↓
Branch deleted · main pulled · task closed
```

---

## 3. PR Checklist (author — before requesting review)

Every box checked before the review request; an unchecked box means the PR is not ready.

- [ ] One logical change; matches the assigned task's scope exactly
- [ ] Title is a valid Conventional Commit (`type(scope): summary`) — it will be the commit on `main`
- [ ] Branch is rebased on current `main`; no conflicts
- [ ] Full local gates green: `make ci` (ruff · mypy · pytest · prettier · eslint · tsc · vitest · build)
- [ ] Only **Files Allowed** from the task assignment touched
- [ ] All **Required Tests** from the task added and passing, including negative/authz cases
- [ ] No direct `fetch()` (frontend); no hand-edits to generated files
- [ ] No commented-out code, debug prints, or TODOs without a `.claude/TODO.md` entry
- [ ] No secrets, no PHI in logs, `.env.example` updated for any new variable
- [ ] Documentation updates from the task completed; ADR written if a non-obvious decision was made
- [ ] Template in §4 completely filled — `None` written where a field doesn't apply

---

## 4. Standard PR Template

Copy into every PR description. Never delete a field — write `None`.

```markdown
<!-- ==================== PULL REQUEST ==================== -->

## Title
<Conventional Commit — identical to the PR title field, e.g.
feat(hospital): add record upload page>

## Related Task
<Task name + link/reference to the assignment (05 template) or TODO entry>

## Milestone
<M2 / M3 / … per .claude/ROADMAP.md>

## Branch
<feature/… — must match 03 §2 naming>

## Summary
<2–4 sentences: what this PR does and why, readable by someone with no context.>

## Scope
<What was implemented — mirror the task's Scope list, marking each item done.>
1. …

## Out of Scope
<What this PR deliberately does NOT include (deferred items, follow-up tasks).>
1. …

## Files Changed
<Grouped summary of the diff — directories touched and why. Flag anything
outside the obvious area and justify it.>
- …

## Tests Executed
<Exact commands run and their results, plus the new tests added.>
- `make ci` — green (backend NNN passed · web NN passed · 3 builds)
- New tests: …

## Documentation Updated
<Docs touched in this PR, or None.>
- …

## Screenshots (if UI)
<Before/after or key states. Mandatory for any user-visible change; else None.>

## Breaking Changes
<API/contract/behavior breaks and their blast radius, or None.
Any breaking API change requires the Lead's prior sign-off — /api/v1 semantics
are immutable per docs/API_GUIDELINES.md.>

## Migration Required
<Alembic revision ID + what it creates/alters + confirmation the up/down/up
round-trip test passes, or None. (Lead-authored PRs only — 02 §3.)>

## Generated Files Updated
<openapi.json / api-client regenerated via `make api-client`? YES (spec diff
summarized + intentional) / NO (endpoints unchanged).>

## ADR Impact
<New ADR added (number + title) / existing ADR relied on (numbers) / None.
ADRs are never edited — only added or superseded, by the Lead.>

## Known Limitations
<Deliberate shortcomings shipped with this PR and where they are tracked
(TODO entry / follow-up task), or None. Undocumented limitations found later
are treated as defects.>

<!-- ================== END PULL REQUEST =================== -->
```

---

## 5. Reviewer Checklist

The Lead (and Claude, for architectural reviews) verifies, in this order — full detail in [`07_CODE_REVIEW_CHECKLIST.md`](07_CODE_REVIEW_CHECKLIST.md):

| Dimension | Verify |
|---|---|
| **Architecture** | Router → service → repository layering; module isolation (no cross-module table access); no new patterns without an ADR; frontend uses generated client only (ADR-001/003) |
| **Security** | Deny-by-default; ADR-013 layers; record/consent reads through the choke point; 404-not-403 on existence leaks; no PHI in logs; no secrets; roles from claims, never request bodies |
| **Testing** | New behavior tested; negative authz tests present for every gated surface; regression test on bugfixes; coverage holds (≥80% records/consent) |
| **Performance** | Pagination on listings; no N+1; no unbounded reads; no blocking calls on the event loop |
| **Naming** | Conventional Commit title; branch naming (03 §2); house naming in code and wire schemas (camelCase JSON) |
| **Documentation** | Endpoint docstrings (purpose/roles/consent/failures); task's doc updates present; ADR added if warranted |
| **Generated Code** | Spec/client regenerated together and only by `make api-client`; spec diff intentional; no hand-edits under `src/generated/` |
| **Migrations** | Alembic only; reversible; naming conventions (`op.f`); single linear head; chain test extended; matches the models exactly |

---

## 6. Merge Criteria

A PR merges when **all** of the following hold — and not before:

1. Template (§4) completely filled; scope matches the task assignment.
2. Author checklist (§3) honestly complete.
3. GitHub CI green; author attests local `make ci` green.
4. Every review conversation resolved **with pushed changes** (SOP §11).
5. Lead approval on the latest push (new pushes invalidate approval).
6. Branch rebased on current `main`; no conflicts.
7. Squash merge, executed by the Lead only; remote branch auto-deleted.

If any criterion regresses between approval and merge (new push, `main` moved with conflicts), the PR returns to review.

---

## 7. Common PR Mistakes

| Mistake | Consequence |
|---|---|
| Vague title (`update code`, `fixes`) | Becomes a meaningless permanent commit on `main`; returned for retitling |
| Empty/partial description | Returned without review — the template is the entry ticket |
| Scope smuggling (files beyond the task's allowlist) | PR closed unreviewed (SOP §10 row 1) |
| Opening with red gates ("CI will catch it") | Reviewer becomes your CI; trust and turnaround suffer |
| Hand-edited `openapi.json` / generated client | Masks contract drift; instant request-changes |
| Missing negative tests on an authz surface | Blocks approval — happy-path-only tests don't prove deny-by-default |
| Resolving threads without pushing the fix | Forces full re-review; erodes reviewer trust |
| Screenshots missing on UI changes | Returned — reviewers don't run three portals to see a button |
| Mega-PR spanning multiple features | Un-reviewable and un-revertible after squash; split it |
| "Known limitation" discovered by the reviewer instead of declared | Treated as a defect, not a footnote |

---

*Maintained by the Lead Developer. Changes via Lead-approved `docs/*` PR only.*
