# PulseOS — Development Workflow (SOP)

> **Document:** `project-management/04_DEVELOPMENT_WORKFLOW.md`
> **Status:** Active — binding for all contributors
> **Scope:** the complete lifecycle of every change, from task assignment to merged code on `main`
> **Related:** [`02_TEAM_RESPONSIBILITIES.md`](02_TEAM_RESPONSIBILITIES.md) (who owns what) · [`03_BRANCH_STRATEGY.md`](03_BRANCH_STRATEGY.md) (branching & merging) · [`docs/CONTRIBUTING.md`](../docs/CONTRIBUTING.md) · [`.claude/CHECKLIST.md`](../.claude/CHECKLIST.md) (Definition of Done)

This is the Standard Operating Procedure for PulseOS. There is exactly **one** way a change reaches `main`, and this document describes it. Ownership boundaries and branch mechanics are defined in documents 02 and 03; this SOP sequences them into the daily engineering loop.

---

## 1. Purpose

One team, one workflow. Every contributor — Lead included — follows the identical procedure so that:

- **Consistency** — every change looks the same in git history, PRs, and reviews; nobody has to learn per-person habits.
- **Predictability** — anyone can tell, at any time, what state a task is in from its branch and PR alone.
- **Quality** — the quality gates (§6) run for every change, every time. Quality is a pipeline property, not a personal virtue.
- **Traceability** — task → branch → PR → squash commit form an unbroken chain; every line on `main` traces back to an assignment and a review.
- **Reduced merge conflicts** — fresh bases, small branches, and early rebases (03 §10) keep integration cheap.
- **Faster reviews** — scoped, gate-green, well-described PRs get reviewed in hours, not days.
- **Stable `main`** — the sum of all of the above: `main` is always demoable, always releasable (03 §3).

Deviation from this SOP is not a style choice — it is how the project has already lost work once (a stale-base parallel implementation that could never merge). Follow the procedure.

---

## 2. High-Level Workflow

```
        Task Assigned
              ↓
     Read Assigned Scope
              ↓
      Pull Latest main
              ↓
    Create Feature Branch
              ↓
 Implement Only Assigned Scope
              ↓
        Local Testing
              ↓
           Commit
              ↓
            Push
              ↓
     Open Pull Request
              ↓
        Code Review
              ↓
  Address Review Comments
              ↓
          Approval
              ↓
        Squash Merge
              ↓
       Delete Branch
```

| Stage | What happens | Detail |
|---|---|---|
| Task Assigned | The Lead assigns a task from `.claude/TODO.md` / ROADMAP to its owner | §3 |
| Read Assigned Scope | Owner reads the task, relevant ADRs, and docs before any code | §3 |
| Pull Latest main | Local `main` synchronized with `origin/main` | §4 |
| Create Feature Branch | `feature/<area>-<slug>` cut from fresh `main` | §4, 03 §7 |
| Implement | Code written strictly inside owned scope, following existing patterns | §5 |
| Local Testing | Full quality gates run and pass locally | §6 |
| Commit | Atomic, Conventional Commits | §7 |
| Push | Branch pushed to `origin` | §8 |
| Open PR | One logical change, description states scope, checklist satisfied | §8 |
| Code Review | Lead review + Claude architectural review | §9, §10 |
| Address Comments | Fix commits pushed to the same branch | §11 |
| Approval | Lead approves once all comments are resolved | §9 |
| Squash Merge | Lead merges; PR title becomes the commit on `main` | §12 |
| Delete Branch | Remote (automatic) and local branch removed | §13 |

---

## 3. Task Assignment

Code starts *after* understanding, never before. When a task is assigned, the owner must:

1. **Read the assigned task completely** — including its milestone context in `.claude/ROADMAP.md` and its entry in `.claude/TODO.md`.
2. **Understand their ownership** — confirm every file the task will touch is inside their domain (`02_TEAM_RESPONSIBILITIES.md` §3–4). If any part isn't, escalate before starting (02 §6).
3. **Read the relevant ADRs** (`.claude/DECISIONS.md`) — e.g., anything touching auth reads ADR-011/013; records work reads ADR-014/015; identity work reads ADR-012.
4. **Read the related documentation** — the doc map in `.claude/CLAUDE.md` points to the right file (API_GUIDELINES for endpoints, DOMAIN_MODEL for entities, SECURITY for anything touching PHI).
5. **Ask questions before coding** if any requirement is unclear. A ten-minute question beats a two-day rework.

> ⚠️ **Never assume missing requirements.** If the task doesn't specify a behavior, that behavior is *undecided*, not *yours to invent*. Ask the Lead. Inventing scope is the same defect as exceeding scope.

---

## 4. Starting Development

The required sequence, every time (full rationale: `03_BRANCH_STRATEGY.md` §7):

```bash
git checkout main          # branch only ever from main — never from another branch
git pull origin main       # synchronize — your teammates' merged work is your new base
git checkout -b feature/doctor-management-ui    # isolated, named workspace
```

Why each step exists:

- **`checkout main`** — branches cut from other branches entangle two unreviewed changes into one lineage.
- **`pull origin main`** — guarantees you build on the current truth. **Stale bases are the single biggest risk in this project**: a branch built on a week-old `main` once produced duplicate models and a colliding migration that had to be discarded entirely. The pull is part of branch creation, not an optional courtesy.
- **`checkout -b feature/…`** — from this point your work is isolated; nothing you do affects anyone until the PR.

If you are resuming an existing branch instead of starting one: rebase it onto today's `main` **before** writing new code (03 §10).

---

## 5. Implementation Rules

While the branch is open, these rules govern every keystroke:

1. **Implement ONLY the assigned scope.** Adjacent improvements, drive-by fixes, and "while I'm here" changes go to the Lead as proposals, not into this branch.
2. **Never redesign architecture.** Architecture and module boundaries are fixed by ADRs. If the assigned task seems to require an architectural change, stop and escalate — the Lead decides and records an ADR first (02 §5–6).
3. **Follow existing patterns.** The codebase is the style guide: router → service → repository on the backend; generated `@pulseos/api-client` only (never `fetch()`) on the frontend; camelCase wire schemas; domain exceptions, not HTTPExceptions, in services. When in doubt, find the closest existing implementation (e.g., the `patients` module, the patient portal pages) and match it.
4. **Keep commits small and logical** (§7) — commit each coherent, green step.
5. **Never mix unrelated work.** One branch = one feature (03 §4). Discovered a bug? File it; its owner fixes it on a `bugfix/*` branch.
6. **No speculative abstractions.** Build for the assigned requirement, not for imagined future ones — "prefer the boring solution" is an engineering principle of this project (`.claude/CLAUDE.md`). The only sanctioned abstractions are the existing external-provider ports (LLM, storage, blockchain, auth, queue).
7. **Respect module boundaries.** Backend modules communicate through service interfaces, never through each other's tables; frontend apps consume shared packages, never each other's code (`docs/SYSTEM_ARCHITECTURE.md` §Isolation).
8. **Never bypass ownership.** Needing a change in someone else's area — an endpoint, a shared component, a migration — is an escalation (02 §6), never a self-service edit.

---

## 6. Local Verification

Nothing is committed, pushed, or PR'd while a local gate is red. The gates are the project's actual tooling:

**Backend** (run inside `backend/`, or via `make` targets from the repo root):

| Gate | Command | Must show |
|---|---|---|
| Formatting | `ruff format --check .` | no diffs |
| Linting | `ruff check .` | `All checks passed!` |
| Types | `mypy` (strict mode) | `no issues found` |
| Tests | `pytest` | all passed — including your new tests |

**Frontend** (run inside `web/`):

| Gate | Command | Must show |
|---|---|---|
| Formatting | `pnpm format:check` (prettier) | all files formatted |
| Linting | `pnpm lint` (eslint) | zero errors |
| Types | `pnpm typecheck` (tsc, strict) | zero errors, all apps |
| Tests | `pnpm test` (vitest) | all passed |
| Build | `pnpm build` | all three portals build |

**Everything at once:** `make ci` runs the exact suite GitHub Actions runs. Green `make ci` locally means green CI remotely — CI exists to *confirm*, not to *discover*.

> ⚠️ **Never push failing code.** Not "to save progress" (push a draft branch without opening the PR instead), and never into an open PR — every push to a PR consumes reviewer attention. Red gates are your signal to keep working, not to hand off.

Additional per-change verification comes from the Definition of Done (`.claude/CHECKLIST.md`): authz negatives tested (wrong role → 403/404), no PHI in logs, migrations reversible, api-client regenerated if endpoints changed.

---

## 7. Commit Workflow

PulseOS uses **Conventional Commits** — `type(scope): imperative summary`, scope = module or package (full table: 03 §9).

```
feat(records): add upload endpoint
fix(auth): validate expired tokens
docs(project): update roadmap
refactor(records): simplify repository
test(consent): add grant revocation tests
chore(ci): update workflow
```

**Atomic commits.** Each commit contains one logical change and is green (builds, tests pass) on its own. Atomic commits make the reviewer's reading order sensible, keep `git bisect` usable, and let a single step be reverted without collateral.

**Logical grouping.** Group by concept, not by save-time. **Prefer multiple commits over one large commit whenever the work has distinguishable steps** — e.g., for a backend feature:

```
feat(records): add MedicalRecord model and migration 0003   ← schema step
feat(records): add upload service and router                ← behavior step
test(records): cover upload RBAC negatives                  ← verification step
```

Three commits like these review far better than one 800-line blob: the reviewer can confirm the schema before reading the behavior, and a flaw in one step doesn't force rereading the others. Since PRs squash on merge (03 §11), branch commits are for the *reviewer's* benefit — they must be honest and buildable, and the **PR title** must be the flawless Conventional Commit that will represent the whole change on `main`.

---

## 8. Push Workflow

1. **Push the branch:**

   ```bash
   git push -u origin feature/doctor-management-ui
   ```

   Push at least at the end of every working session — unpushed work is invisible and unbacked-up.

2. **Open the Pull Request** (when the task is complete and §6 is fully green):
   - **Title:** a Conventional Commit — it becomes the permanent squash-commit message.
   - **Description:** what the change does, the task it implements, the scope it touches (and explicitly what it does *not* touch), how it was tested, and screenshots for any UI change.
   - Confirm the PR checklist from `.claude/CHECKLIST.md` (one logical change, CI green, no commented-out code or stray TODOs).

3. **Keep the PR description current.** If review reshapes the change, update the description — it is the record future readers will trust.

4. **Request review** from the Lead. A PR nobody was asked to review is a PR nobody reviews.

---

## 9. Pull Request Workflow

What happens between "PR opened" and "merged":

1. **Lead review** — the Lead reviews every PR (02 §4) in the order defined by `docs/CONTRIBUTING.md`: (1) module-isolation or consent-enforcement violations → instant block; (2) presence of negative-authz tests; (3) is it the simplest thing that works; (4) style last.
2. **Claude architectural review** — for substantive changes (new endpoints, schema, services, or anything near a security invariant), the Lead requests a review from Claude (the project's Senior Engineer) against the architecture, ADRs, and checklist. Its findings are logged as review comments with the same standing as any reviewer's; the Lead decides which are binding.
3. **Review comments** — posted on the PR. Comments are about the code, never the person; each states what must change and why (rule, ADR, or defect).
4. **Fix commits** — the author addresses comments with new commits on the same branch (`fix review: …` style is fine — squash erases them). No force-push rewrites during an active review except a `main` rebase, announced in the PR.
5. **Re-review** — the author re-requests review after pushing fixes. New pushes invalidate prior approval.
6. **Approval** — granted when every comment is resolved and gates are green.
7. **Squash merge** — performed by the Lead only (§12).

Target turnaround: review within **24 hours** of request (`docs/CONTRIBUTING.md`); authors respond to comments with the same urgency. A PR stalled for more than two days is raised in the next sync.

---

## 10. Code Review Expectations

What reviewers check, in priority order:

| # | Dimension | What is verified |
|---|---|---|
| 1 | **Scope** | Every touched file is inside the author's ownership (02 §4); the diff matches the PR description; nothing unrelated smuggled in. Out-of-scope files → PR closed, not reviewed. |
| 2 | **Architecture** | Layering intact (router → service → repository); module isolation respected; no new patterns without an ADR; frontend uses the generated client only. |
| 3 | **Security** | Deny-by-default authz; ADR-013 layers respected; consent/record reads through the single choke point; no PHI in logs; no secrets in code; 404-not-403 where existence must not leak. |
| 4 | **Testing** | New behavior has tests; every authz surface has *negative* tests; bugfixes carry a regression test; coverage holds on core modules (≥80% on `records`/`consent`). |
| 5 | **Naming** | Follows house conventions (models, schemas, camelCase wire fields, branch/commit naming); names say what things are. |
| 6 | **Performance** | No N+1 queries; pagination on listings; no unbounded reads; async rules respected (no blocking calls on the event loop). |
| 7 | **Documentation** | Endpoint docstrings (purpose, roles, consent requirement, failure modes); affected docs updated; ADR written if a non-obvious decision was made. |
| 8 | **Generated files** | `openapi.json` / `api-client` regenerated when endpoints changed — and *only* by generation; any spec diff is intentional and explained. |
| 9 | **Migrations** | Alembic only, Lead-authored, reversible, naming conventions followed, single linear head, chain test updated. |
| 10 | **ADRs** | The change complies with every applicable ADR; no ADR was edited outside the Lead's authority. |

---

## 11. Resolving Review Comments

How authors respond to review:

- **Do not argue defensively.** A comment is about the code. If the reviewer misread something, clarify with facts (a pointer to the line, a doc, an ADR) — not with justification of effort.
- **Ask for clarification** when a comment is ambiguous, *before* implementing a guess at what it meant.
- **Disagreement is allowed, once and with reasons.** State the technical case in the thread; the Lead's decision is final (02 §4). Then either implement or accept.
- **Push fixes** as new commits to the same branch and re-request review (§9).
- **Mark conversations resolved only after the change is pushed** — never resolve a thread to make the PR look clean. The reviewer verifies resolutions; a prematurely-resolved thread costs a full re-review round.
- **Batch your fixes.** Address all comments, then push once — not one push per comment.

---

## 12. Merge Process

- **Only the Lead merges.** Authors never merge their own PRs — including the Lead, whose PRs still require the review step before self-executing the merge.
- **Squash Merge is the standard** (03 §11): one feature = one commit on `main`; the PR title becomes the commit message; rollback is a single `git revert`.
- **The merged branch is deleted** on the remote immediately (automatic on squash-merge).
- **Everyone syncs afterwards:** the next `git pull origin main` by each member picks up the change. Members with open branches rebase onto the new `main` promptly (03 §10) — the earlier the rebase, the smaller the conflict.

---

## 13. Post-Merge Responsibilities

The task is not finished at merge. The author must:

1. **Delete the local feature branch:**
   ```bash
   git checkout main && git pull origin main && git branch -d feature/…
   ```
2. **Pull the latest `main`** (done above) so the next branch starts from the merged truth.
3. **Verify integration if requested** — when the Lead asks, run the affected demo flow against merged `main` (e.g., portal page against the live backend) and confirm in the task thread.
4. **Close the related task** — tick it in `.claude/TODO.md` via the PR or report completion to the Lead, who updates TODO/SESSION records. A merged PR with an open task is untracked work.

---

## 14. Development Best Practices

Condensed from 02/03 — the habits that keep the loop fast:

- **Pull latest before coding** — every session, without exception (§4).
- **Commit frequently** — every coherent green step; small commits are free, lost work is not.
- **Keep PRs small** — a 200-line PR is reviewed in an hour; land big work as sequenced small PRs.
- **Avoid long-lived branches** — a branch older than a week is a problem to split or escalate (03 §13).
- **Document important decisions** — non-obvious choices become ADR proposals to the Lead; everything else goes in the PR description, not in tribal memory.
- **Keep generated files synchronized** — endpoint changes and the regenerated `api-client` land in the same PR; portal owners rebase to consume new types. Never hand-edit `web/packages/api-client/src/generated/` or `openapi.json`.
- **Run `make ci` before every push** — it is the same suite as GitHub Actions; local green means remote green.
- **Write the PR description for a stranger** — six weeks from now, that stranger is you.

---

## 15. Common Mistakes

The failure modes this SOP exists to prevent — several observed in this project:

| Mistake | Why it hurts here | Rule broken |
|---|---|---|
| **Working on a stale branch** (skipped `git pull`) | Already produced a parallel implementation with duplicate models and a colliding Alembic migration — the entire commit had to be discarded | §4 |
| **Implementing another member's scope** | Two owners for one concept → incompatible versions of the truth; instant PR rejection | §5.8, 02 §5 |
| **Skipping tests** ("it works on my machine") | Red CI after push, broken `main` risk, reviewer time wasted; authz gaps ship silently | §6 |
| **Changing ADRs without approval** | ADRs are the project's decided architecture; edits outside the Lead's authority undo settled decisions | §5.2, 02 §5 |
| **Editing generated files manually** | Hand edits to `api-client` mask spec drift and vanish at next generation | §14 |
| **Mixing multiple features in one PR** | Un-reviewable; one rejected part blocks the rest; unrevertible after squash | §5.5, 03 §4 |
| **Opening a PR with red gates** | The reviewer becomes your CI; trust and turnaround both suffer | §6 |
| **Resolving review threads without pushing the fix** | Forces a full re-review; erodes the reviewer's ability to trust resolutions | §11 |
| **Inventing unstated requirements** | Speculative scope = unreviewed product decisions in code | §3 |
| **Letting a branch live for weeks** | Compounding rebase cost; the eventual merge is a rewrite | §14, 03 §13 |

---

## 16. Quick Reference Checklist

Print-worthy. Every box, every change, in order:

```
☐ Task understood            (scope + ADRs + docs read; questions asked — §3)
☐ Latest main pulled         (git checkout main && git pull origin main — §4)
☐ Feature branch created     (feature/<area>-<slug> from fresh main — §4)
☐ Scope followed             (only owned files; no architecture changes — §5)
☐ Tests passed               (make ci fully green: ruff · mypy · pytest ·
                              prettier · eslint · tsc · vitest · build — §6)
☐ Commit created             (atomic, Conventional Commits — §7)
☐ Push completed             (git push -u origin feature/… — §8)
☐ PR opened                  (Conventional title, scope-stating description — §8)
☐ Claude review requested    (architectural review for substantive changes — §9)
☐ Lead approval received     (all comments resolved, re-review after fixes — §9–11)
☐ Squash merged              (by the Lead; PR title = commit on main — §12)
☐ Branch deleted             (remote + local; main re-pulled; task closed — §13)
```

---

*Maintained by the Lead Developer. This SOP changes only via a Lead-approved `docs/*` PR, and its terminology stays synchronized with `02_TEAM_RESPONSIBILITIES.md` and `03_BRANCH_STRATEGY.md`.*
