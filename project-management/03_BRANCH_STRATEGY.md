# PulseOS — Git Branch Strategy

> **Document:** `project-management/03_BRANCH_STRATEGY.md`
> **Status:** Active — binding for all contributors
> **Related:** [`02_TEAM_RESPONSIBILITIES.md`](02_TEAM_RESPONSIBILITIES.md) · [`docs/CONTRIBUTING.md`](../docs/CONTRIBUTING.md) · [`.claude/CHECKLIST.md`](../.claude/CHECKLIST.md)
>
> **Naming note:** this document standardizes the long-form prefixes already used in the
> repository's history (`feature/medical-records`, `feature/m0.3-patient-web`). Where
> `docs/CONTRIBUTING.md` shows short prefixes (`feat/`, `fix/`), the branch names in **this**
> document are canonical; the short forms remain correct for **commit messages** (§9).

---

## 1. Purpose

A branching strategy is not bureaucracy — it is the mechanism that lets three people build one system without breaking each other. Every rule below exists for one of these reasons:

- **Stability of `main`.** `main` is always demoable and always releasable. A broken `main` blocks every member simultaneously; the strategy makes that state structurally impossible rather than merely discouraged.
- **Parallel development.** The Lead builds backend milestones while Members 1 and 2 build three portals. Isolated branches let all three streams move at full speed without stepping on each other's files.
- **Code review.** Every change enters `main` through a Pull Request reviewed by the Lead. Branches are the unit of review: one branch = one reviewable, rejectable, mergeable change.
- **Easy rollback.** With squash merges, one feature = one commit on `main`. Reverting a bad feature is a single `git revert`, not archaeology.
- **Reduced merge conflicts.** Short-lived branches cut from the latest `main` and rebased regularly keep diffs small. This project has already seen what a stale base produces: a parallel, incompatible implementation that could not merge. Never again.
- **Accountability.** A branch has one author and one owned scope (per `02_TEAM_RESPONSIBILITIES.md`). The branch name says what is being built; the PR says who is responsible for it.

---

## 2. Branch Overview

| Branch | Purpose | Created by | Base | Lifetime |
|---|---|---|---|---|
| `main` | The single source of truth. Always stable, always demoable. | — (permanent) | — | Permanent |
| `feature/*` | One new feature or milestone slice | Task owner | Latest `main` | Days — deleted after merge |
| `bugfix/*` | Fix for a defect found in `main` (non-urgent) | Task owner | Latest `main` | Hours–days — deleted after merge |
| `hotfix/*` | Urgent fix for a defect breaking the demo flow or a live deployment | Lead (or owner, Lead notified immediately) | Latest `main` | Hours — deleted after merge |
| `docs/*` | Documentation-only changes (`docs/`, `project-management/`, `.claude/`, README) | Any member (own docs scope) | Latest `main` | Hours–days — deleted after merge |
| `refactor/*` | Behavior-preserving restructuring (no feature, no fix) | Task owner (Lead approval required first — see §5 note) | Latest `main` | Days — deleted after merge |

### Branch types in detail

- **`main`** — protected. Nothing is developed here; nothing is pushed here directly. It advances only by squash-merged, Lead-approved PRs. At any commit on `main`, the demo flows of all completed milestones must work (`docs/CONTRIBUTING.md` rule 1: *"`main` is always demoable"*). If a merge breaks the demo flow, fixing it preempts everything.
- **`feature/*`** — the default working branch. Scoped to exactly one feature or one milestone slice from `.claude/TODO.md`/ROADMAP. All application work — backend milestones by the Lead, portal pages by Members 1 and 2 — happens on feature branches.
- **`bugfix/*`** — for defects in merged code that are not demo-blocking. Same lifecycle as a feature branch, but the PR must reference the observed defect (steps to reproduce, expected vs. actual) and include a regression test.
- **`hotfix/*`** — for defects that break a demo-critical flow or a deployed environment. Same PR process (review is never skipped), but prioritized above all other work by both author and reviewer. Kept minimal: fix + regression test, nothing else.
- **`docs/*`** — documentation-only. May not touch application code, generated files, or configuration that affects builds. Docs-only changes skip the heavy CI jobs but still merge via reviewed PR — *"Docs PRs are real PRs — same review bar"* (`docs/CONTRIBUTING.md`).
- **`refactor/*`** — restructuring with zero behavior change (proven by the untouched test suite). Because refactors ripple across files, they carry the highest conflict risk: keep them small, land them fast, and never mix them with features.

> **Note — no `develop`, no release branches.** PulseOS deliberately uses trunk-based development with short-lived branches. A three-person team with one integrator gains nothing from GitFlow's extra layers; milestone gates (`.claude/ROADMAP.md`) play the role of releases.

---

## 3. Main Branch Rules

`main` is always deployable and stable. These rules are absolute:

1. **Never commit directly to `main`.** No exceptions — not for "one-line" changes, not for docs, not for the Lead.
2. **Never force-push.** To `main` or to any branch someone else may have pulled. History on `main` is immutable.
3. **Never develop on `main`.** Your local `main` exists only to be pulled from and branched from.
4. **Only merged Pull Requests may enter `main`.** There is no other path.
5. **Every merge must pass review.** The Lead reviews and approves every PR (`02_TEAM_RESPONSIBILITIES.md` §4). Self-merge without review is prohibited, including for the Lead's own PRs, which are opened as PRs and held to the same checklist.
6. **Every merge must pass the local quality gates** before the PR is even opened: backend — `ruff format --check`, `ruff check`, `mypy` (strict), `pytest`; web — `pnpm format:check`, `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build`. `make ci` runs the full set. CI on GitHub confirms; it does not discover.

---

## 4. Feature Branch Rules

Feature branches are where all product work happens.

**Naming:** `feature/<area>-<short-slug>` — lowercase, hyphen-separated, specific enough that the branch list reads like a status board.

```
feature/patient-ui
feature/hospital-dashboard
feature/medical-records
feature/consent
feature/ai-rag
```

**Rules:**

1. **Branch from the latest `main`.** Always `git pull` first (§7). A stale base is how duplicate, unmergeable work is born.
2. **One feature per branch.** If you find yourself typing "and" into the branch name, split it. Mixed branches are un-reviewable and un-revertible.
3. **Stay inside your assigned scope.** The branch may only touch files you own (`02_TEAM_RESPONSIBILITIES.md` §3). A feature branch containing another member's files is rejected at review without further reading.
4. **Keep commits logical** (§9): each commit is one coherent step that builds and passes tests.
5. **Push early, push often.** An unpushed branch is invisible work and an unrecoverable laptop away from being lost.
6. **Delete the branch after merge** — both remote (GitHub does this on squash-merge) and local (`git branch -d`). Merged branches are noise.

---

## 5. Bugfix Branch Rules

Create a `bugfix/*` branch when code already merged to `main` misbehaves and the fix is not demo-blocking (demo-blocking → `hotfix/*`).

**Naming:** `bugfix/<area>-<symptom>`

```
bugfix/profile-validation
bugfix/upload-timeout
```

**Rules:**

1. Reproduce the defect first; state the reproduction in the PR description (observed vs. expected).
2. **Every bugfix ships with a regression test** that fails before the fix and passes after. A fix without a test is half a fix.
3. Fix only the defect. Improvements you noticed along the way become their own branch.
4. The fix is made by the **owner of the defective area** — a portal bug by its portal owner, anything backend by the Lead. Finding a bug in someone else's area means filing it, not fixing it.

> **Note on `refactor/*`:** refactors follow the same rules as features, with one addition — because "behavior-preserving" claims are architecture-adjacent, agree on the refactor's scope with the Lead **before** starting (`02_TEAM_RESPONSIBILITIES.md` §6).

---

## 6. Documentation Branch Rules

Use `docs/*` for changes that touch only documentation: `docs/`, `project-management/`, `.claude/` process files, READMEs, and doc-comments that don't change code.

**Naming:** `docs/<topic>`

```
docs/project-management
docs/api-guidelines
```

**Rules:**

1. **Zero code in a docs branch.** If the change also needs code, it is a feature/bugfix branch whose PR updates the docs alongside the code (documentation duties travel with the change — `docs/CONTRIBUTING.md`).
2. Documentation ownership applies: architecture/backend/process docs are the Lead's; portal UX docs belong to the respective portal owner.
3. ADRs (`.claude/DECISIONS.md`) are **never** modified on a docs branch by Members 1 or 2 — ADR changes are Lead-only and usually accompany the implementing PR.
4. Same PR + review process as everything else; CI's heavy jobs are skipped automatically for docs-only diffs.

---

## 7. Branch Creation Workflow

The complete sequence, every time — no shortcuts:

```bash
# 1. Return to main — never branch from another branch.
git checkout main

# 2. Synchronize with the remote — your local main is only trustworthy after this.
git pull origin main

# 3. Cut the branch — you are now isolated from everyone else's work.
git checkout -b feature/hospital-dashboard
```

Why each step exists:

| Step | Why it exists |
|---|---|
| `git checkout main` | Branches cut from other branches inherit unreviewed commits, entangling two PRs. Every branch descends directly from `main`. |
| `git pull origin main` | Guarantees you build on what your teammates have already merged. **Skipping this step is the single most expensive mistake available in this repository** — it has already produced a parallel implementation with a conflicting migration that could never merge. |
| `git checkout -b feature/…` | Creates your isolated workspace with a name that declares its scope. From here on, nothing you do can affect anyone else until you open a PR. |

---

## 8. Daily Development Workflow

What every developer does, every working day:

1. **Pull the latest `main`** (`git checkout main && git pull origin main`) — even if you pulled yesterday. `main` moves.
2. **Create (or rebase) your feature branch.** New task → new branch (§7). Continuing a task → rebase your branch onto today's `main` (§10) before writing new code.
3. **Implement only the assigned task**, only inside your owned directories (`02_TEAM_RESPONSIBILITIES.md`). Scope growth → stop and escalate, don't code.
4. **Run your local gates as you go** — don't batch a week of work before discovering the type checker disagrees.
5. **Commit** in logical units with Conventional Commit messages (§9).
6. **Push** your branch to the remote at least at the end of each session (`git push -u origin feature/…`).
7. **Open the PR** when the task is complete and every local gate is green — one logical change, checklist satisfied, scope stated in the description.

---

## 9. Commit Strategy

PulseOS uses **[Conventional Commits](https://www.conventionalcommits.org/)**: `type(scope): imperative summary`. The scope is the module or package touched (`docs/CONTRIBUTING.md`).

**Types and examples:**

| Type | Use for | Example |
|---|---|---|
| `feat` | New functionality | `feat(records): add upload endpoint` |
| `fix` | Defect corrections | `fix(auth): validate expired tokens` |
| `docs` | Documentation only | `docs(project): update roadmap` |
| `refactor` | Behavior-preserving restructuring | `refactor(records): simplify repository` |
| `test` | Adding/adjusting tests only | `test(consent): add grant revocation tests` |
| `chore` | Tooling, CI, dependencies, housekeeping | `chore(ci): update workflow` |

**Atomic commits.** A commit is *atomic* when it contains exactly one logical change, the code builds, and the tests pass at that commit. Atomic commits make review readable, `git bisect` usable, and partial reverts possible.

**Logical grouping.** Group by *what changed conceptually*, not by *when you happened to save*:

- ✅ `feat(records): add MedicalRecord model and migration 0003` → then `feat(records): add upload service and router` → then `test(records): cover RBAC negatives`
- ❌ `wip`, `more changes`, `fix stuff`, `final`, `final2`

Since PRs are squash-merged (§11), your branch commits become the reviewer's reading order and your own safety net — they don't need to be perfect, but they must be honest and buildable. The **PR title** must be a flawless Conventional Commit, because it becomes the permanent commit message on `main`.

---

## 10. Synchronizing with Main

**When to sync your feature branch:**

- `main` has moved and you're still working (sync at least daily on active branches);
- before opening a PR — always;
- when the Lead asks you to, after a merge that touches files near yours.

**How — rebase, never merge-from-main:**

```bash
# From your feature branch:
git fetch origin
git rebase origin/main

# If conflicts appear: resolve each file, then
git add <resolved-files>
git rebase --continue

# Re-run your full local gates after every rebase, then push.
# The branch history was rewritten, so a force push IS required here —
# use the safe variant, and only ever on your own feature branch:
git push --force-with-lease
```

**Why rebase is preferred:**

- **Linear history.** Your branch replays *on top of* current `main`, so the PR diff shows exactly your changes — no `Merge branch 'main' into …` noise commits polluting the review.
- **Conflicts surface at the right commit.** Rebase presents conflicts one commit at a time, where the conflicting change was made — far easier to resolve correctly than one giant merge-commit conflict.
- **Squash-merge synergy.** Since the PR squashes anyway (§11), merge commits inside the branch add nothing and confuse the reviewer's timeline.

> ⚠️ **Force-push discipline:** `--force-with-lease` is legal **only** on your own feature branch after a rebase. It is never legal on `main` (§3) or on any branch with more than one author.

---

## 11. Merge Strategy

**All Pull Requests are merged with *Squash and Merge*, executed by the Lead, unless the Lead explicitly decides otherwise for a specific PR** (e.g. a multi-part milestone where individual commits carry review value).

Why squash merge:

- **Cleaner history.** `main` reads as a sequence of completed features, one line each — the roadmap made literal. `git log --oneline main` is the project changelog's skeleton.
- **One feature = one commit.** The unit of work, review, and history are the same thing. Branch-internal noise (`fix typo`, `address review comments`) never reaches `main`.
- **Easier rollback.** Reverting a feature is `git revert <one-sha>`. No hunting for the commit range, no partially-reverted features.

Mechanics: the Lead merges after approval; the PR title (a Conventional Commit, §9) becomes the squash commit's message; the remote branch is deleted on merge.

---

## 12. Branch Protection Rules

These are enforced as GitHub branch-protection settings on `main` where the platform supports them, and as binding team policy everywhere else:

1. **No direct pushes to `main`** — all changes via PR, including the Lead's.
2. **Review required** — one approval from the Lead on every PR; re-approval after new pushes to the branch.
3. **Local tests required** — the full local gate (`make ci`) is green before the PR is opened; GitHub CI must be green before merge.
4. **Resolve merge conflicts before review** — a conflicted PR is not reviewable; rebase onto `main` first (§10).
5. **Never merge failing code** — no "we'll fix it on main," no merging with red CI, no skipped tests to make the build pass.
6. **No force pushes to `main`; no branch deletion of `main`** — platform-enforced.
7. **Scope check is part of protection** — a PR touching files outside the author's ownership (`02_TEAM_RESPONSIBILITIES.md` §4) is closed, not reviewed.

---

## 13. Branch Lifecycle Diagram

```
                        main  (protected, always demoable)
                          │
             git pull ────┤
                          ▼
              feature/hospital-dashboard        ← cut from latest main (§7)
                          │
                          ▼
                      commits                   ← atomic, Conventional (§9)
                          │
                          ▼
                        push                    ← git push -u origin … (§8)
                          │
                          ▼
                     open PR                    ← gates green, scope stated
                          │
                          ▼
                    Lead review                 ← isolation → tests → simplicity → style
                          │
                          ▼
                       fixes                    ← push to same branch, re-review
                          │
                          ▼
                     approval
                          │
                          ▼
                 squash merge → main            ← PR title becomes the commit (§11)
                          │
                          ▼
                  delete branch                 ← remote + local; cycle restarts
```

Typical cycle time: **1–3 days** from branch creation to deletion. If a branch is older than a week, something is wrong — split it or escalate.

---

## 14. Best Practices

- **Small PRs win.** A 200-line PR gets a thorough review in an hour; a 2,000-line PR gets a tired skim. Land milestone work as a sequence of small PRs (`docs/CONTRIBUTING.md` rule 2).
- **Pull latest before coding — every session.** The cost is five seconds; the alternative has already cost this project a full rework.
- **Avoid long-lived branches.** Every day a branch lives, its merge cost compounds. Ship slices.
- **Commit frequently.** Small commits are free; lost work is not. Commit whenever a coherent step is done and green.
- **Keep generated files synchronized.** When the Lead changes the API, the regenerated client (`web/packages/api-client/`) lands in the same PR; portal owners rebase and consume the new types. If the spec and client disagree, the PR is wrong (`docs/API_GUIDELINES.md`).
- **Do not manually edit generated code.** `web/packages/api-client/src/generated/` and `openapi.json` are machine-owned. Hand edits are overwritten by the next generation and mask contract drift.
- **Resolve conflicts early.** Rebase the moment `main` moves under you (§10), while the conflict is small and your context is fresh — not at PR time under deadline pressure.
- **Name branches like status reports.** `feature/doctor-management-ui` tells the whole team what's in flight; `feature/stuff2` tells them nothing.
- **Run the exact CI commands locally.** `make ci` is CI. Green locally means green remotely; surprises in CI mean your local loop is broken — fix that first.

---

## 15. Common Mistakes

Each of these has a rule above; they are listed here because they are the ways branching *actually* fails in small teams:

| Mistake | Consequence | Prevention |
|---|---|---|
| **Working directly on `main`** | Unreviewed code in the trunk; everyone's base is now polluted | §3 — branch first, always |
| **Branching from a stale `main`** (forgetting to pull) | Duplicate/conflicting implementations that cannot merge — *this has happened in this repository* (a conflicting migration and duplicate models built on a week-old base) | §7 — `pull` is part of branch creation, not optional |
| **Mixing unrelated features in one branch** | Un-reviewable PR; one rejected feature blocks the other; revert impossible | §4 — one feature per branch |
| **Large, unfocused commits** (`wip`, `final2`) | Review by archaeology; bisect useless | §9 — atomic commits, Conventional messages |
| **Stale branches living for weeks** | Compounding conflicts; rebases become rewrites | §14 — ship slices; escalate stuck work |
| **Editing generated files manually** | Contract drift hidden until runtime; changes silently overwritten | §14 — regenerate via `make api-client`, never hand-edit |
| **Implementing outside assigned scope** | Ownership collisions, duplicated work, instant PR rejection | `02_TEAM_RESPONSIBILITIES.md` §5–6 — escalate, don't improvise |
| **Force-pushing shared history** | Teammates' clones break; work is lost | §10 — `--force-with-lease`, own feature branches only |
| **Merging with red CI "just this once"** | `main` stops being trustworthy; everyone's next branch starts broken | §12 — never merge failing code, no exceptions |

---

*Maintained by the Lead Developer. Proposals for changes to this strategy are welcome from any member and are adopted only via a Lead-approved `docs/*` PR.*
