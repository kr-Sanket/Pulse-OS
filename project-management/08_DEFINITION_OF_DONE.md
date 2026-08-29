# PulseOS — Definition of Done

> **Document:** `project-management/08_DEFINITION_OF_DONE.md`
> **Status:** Active — binding for every feature, bugfix, and task
> **Related:** [`.claude/CHECKLIST.md`](../.claude/CHECKLIST.md) (per-PR quality gates) · [`04_DEVELOPMENT_WORKFLOW.md`](04_DEVELOPMENT_WORKFLOW.md) · [`05_TASK_ASSIGNMENT_TEMPLATE.md`](05_TASK_ASSIGNMENT_TEMPLATE.md) · [`07_CODE_REVIEW_CHECKLIST.md`](07_CODE_REVIEW_CHECKLIST.md)

---

## 1. Purpose

"Done" is a binary, verifiable state — not a feeling, an estimate, or "it works on my machine." A task is Done when **every** requirement in §2–§8 holds and the checklist in §9 is fully ticked. Anything less is *in progress*, regardless of how much code exists.

A shared Definition of Done exists because the alternative is expensive: half-done work merges, `main` stops being demoable, milestones "complete" on paper while their gates fail in practice, and the same task gets reopened three times. In PulseOS, a phase is done only when its ROADMAP gate passes — and gates are built out of Done tasks.

**Done is claimed by the author and verified by the Lead.** If the Lead can't verify a claim from the PR alone, it isn't Done.

---

## 2. Coding Requirements

- The **entire assigned scope** (task's Scope list, 05 §3) is implemented — no partial items, no "90% done."
- **Nothing beyond the assigned scope** is implemented — extra features make a task *not Done*, not extra Done.
- Code follows existing patterns (router → service → repository; generated api-client only; house naming) and stays inside the author's owned files.
- Fully typed: mypy strict clean (backend), tsc strict with no unjustified `any` (frontend).
- No commented-out code, debug prints, or dead branches; TODOs only with a matching `.claude/TODO.md` entry.
- No secrets in code; new configuration documented in `.env.example`.

## 3. Testing Requirements

- Every new behavior has tests; every bugfix has a regression test that fails without the fix.
- **Negative tests are mandatory on authorization surfaces**: wrong role → 403, unauthenticated → 401, out-of-scope resource → 404 — not just the success path.
- Consent- or records-touching changes test the enforcement path explicitly.
- External services (Firebase, S3/MinIO, Redis, LLM, chain) are faked — no live calls in the suite.
- The **full** local gate is green, not just the new tests: `ruff format --check` · `ruff check` · `mypy` · `pytest` (backend); `prettier` · `eslint` · `tsc` · `vitest` · `build` (frontend) — i.e. `make ci`.
- Coverage holds: ≥80% on `records`/`consent`; no test skipped, deleted, or weakened to get to green.

## 4. Documentation Requirements

- Docs matching the change are updated (map in `.claude/CLAUDE.md`) — behavior changes never ship doc-silent.
- API endpoints carry docstrings: purpose, allowed roles, consent requirement, failure modes.
- Non-obvious decisions are recorded as ADRs (Lead-authored); `CHANGELOG.md` updated for milestone-visible changes.
- The task's **Documentation Updates** list (05 §3) is completed; portal owners keep their screen inventories current.
- At session/task end: `.claude/SESSION.md` and `.claude/TODO.md` reflect reality.

## 5. Architecture Requirements

- All applicable ADRs complied with; **no ADR edited** — only added or superseded, by the Lead.
- Module isolation intact: no cross-module table access; cross-module needs go through service interfaces.
- No new abstractions, modules, or patterns beyond the assigned scope; external providers stay behind their existing ports.
- Database changes exist **only** as Lead-authored, reversible Alembic migrations on a single linear head, with the chain test extended.
- Security invariants untouched: consent choke point, deny-by-default, append-only audit, SYSTEM_ADMIN-never-reads-PHI.

## 6. Review Requirements

- PR opened using the standard template (06 §4), completely filled, with a Conventional-Commit title.
- Lead review completed; Claude architectural review completed for substantive changes (SOP §9).
- **Every** review conversation resolved *with pushed changes* — no self-resolved threads.
- Approval granted on the **latest** push; re-review obtained after any post-approval change.

## 7. Merge Requirements

- Branch rebased on current `main`; zero conflicts.
- GitHub CI green on the merge candidate.
- Squash-merged **by the Lead** (03 §11); PR title became the commit on `main`.
- Remote branch deleted at merge; local branch deleted after; author re-pulled `main`.

## 8. Deployment Requirements

Until cloud deployment lands (ADR-009, M7), "deployable" means **demoable from a clean checkout**:

- `main` still passes the demo flows of all completed milestones after the merge — if it doesn't, fixing it preempts everything.
- The change works via the standard local stack path (`make up` → `alembic upgrade head` → `scripts/seed.py` → run) — no manual DB pokes, no undocumented setup steps.
- Anything that *cannot* yet be live-verified (pending PO ops items — Docker/MinIO/Firebase config) is explicitly listed in the PR's **Known Limitations**, tracked in TODO, and verified as part of the milestone gate demo before the milestone itself is called Done.
- From M7 on: the release checklist in [`09_RELEASE_PROCESS.md`](09_RELEASE_PROCESS.md) additionally applies to deployed environments.

---

## 9. Feature Checklist

The task is Done when every box is checked — in this order:

```
☐ Scope completed              (every Scope item implemented; nothing extra)
☐ Tests passing                (pytest + vitest, incl. new negative/authz tests)
☐ Lint passing                 (ruff format --check · ruff check · prettier · eslint)
☐ Types passing                (mypy strict · tsc strict, all apps)
☐ Build passing                (pnpm build — all three portals)
☐ Documentation updated        (docs map · docstrings · CHANGELOG · TODO/SESSION)
☐ Generated files regenerated  (make api-client if endpoints changed; no hand edits)
☐ Migration verified           (reversible, chain test extended — or N/A)
☐ PR opened per template       (06 §4 complete; Conventional title)
☐ PR approved                  (Lead — latest push; all threads resolved w/ changes)
☐ Squash merged                (by the Lead; main still demoable)
☐ Branch deleted               (remote + local; main re-pulled; task closed in TODO)
```

---

## 10. Examples of Done vs Not Done

| Scenario | Verdict | Why |
|---|---|---|
| Upload page implemented, all states handled, 9 vitest tests green, screenshots in PR, approved, squash-merged, branch gone, TODO ticked | ✅ **Done** | Every §2–§8 requirement verifiable from the PR |
| "The endpoint works — I tested it with curl" | ❌ Not Done | No automated tests; §3 fails. Manual verification is evidence for *you*, not a deliverable |
| Feature merged, but the 403-wrong-role test is "coming in a follow-up PR" | ❌ Not Done | Negative authz tests are part of the feature, not a sequel (§3) |
| Code complete and green locally, PR open, review comments unaddressed for four days | ❌ Not Done | Done includes reviewed and merged (§6–§7) — an open PR is in progress |
| Records endpoint added; `openapi.json`/api-client not regenerated | ❌ Not Done | Generated files ship with the endpoint change (§9); the contract is now lying |
| Migration merged; downgrade raises; "we'll never downgrade anyway" | ❌ Not Done | Reversibility is a hard requirement (§5, DATABASE_DESIGN) |
| Feature merged and demoable; one edge case deliberately deferred, listed under Known Limitations with a TODO entry, accepted by the Lead | ✅ **Done** | Declared, tracked, accepted limitations are compatible with Done — undeclared ones are defects |
| M2 backend merged with 194 green tests and fake-verified gates; live MinIO run pending as a tracked PO ops item | ✅ **Task Done** / ⏳ milestone gate pending | The *task* meets §2–§8; the *milestone* is Done only when its ROADMAP gate demo passes — the two are tracked separately |
| "Done, just needs a small cleanup pass later" | ❌ Not Done | If it needs work, it isn't Done. Schedule the work or finish it now |

---

*Maintained by the Lead Developer. This definition tightens over time (e.g. deployment criteria at M7); it never loosens per-task.*
