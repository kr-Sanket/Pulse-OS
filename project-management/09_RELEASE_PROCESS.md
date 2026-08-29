# PulseOS — Release Process

> **Document:** `project-management/09_RELEASE_PROCESS.md`
> **Status:** Active — owned and executed by the Lead Developer (Release Management, 02 §3.1)
> **Related:** [`03_BRANCH_STRATEGY.md`](03_BRANCH_STRATEGY.md) · [`08_DEFINITION_OF_DONE.md`](08_DEFINITION_OF_DONE.md) · [`.claude/ROADMAP.md`](../.claude/ROADMAP.md) · [`CHANGELOG.md`](../CHANGELOG.md)

---

## 1. Purpose

This document defines how completed work reaches `main` — and how `main` becomes a *release*.

In PulseOS, `main` is the release line: trunk-based, always demoable, no `develop` or release branches (03 §2). A **release** is a verified state of `main` that closes a milestone gate (`.claude/ROADMAP.md`) and is recorded in `CHANGELOG.md` — versioning is **milestone-based pre-1.0** (0.1.0 = M0.1 scaffold, and so on). From M7 onward, a release additionally means a cloud deployment (ADR-009).

One person — the Lead — executes every merge and every release, so the pipeline from feature branch to released milestone has exactly one integration authority and zero ambiguity.

---

## 2. Release Lifecycle

```
Feature            (owner implements on feature/* — SOP §4–7; DoD §2–5 met)
   ↓
PR                 (template 06 §4; gates green; Conventional title)
   ↓
Review             (Lead + Claude architectural review — 07 checklist)
   ↓
Approval           (latest push; all threads resolved with changes)
   ↓
Merge              (Lead squash-merges; one feature = one commit on main)
   ↓
Verification       (post-merge checks — §5; main still demoable)
   ↓
Release            (milestone gate demo passes → CHANGELOG entry + tag;
                    M7+: deploy to the hosted environment)
```

Each stage is a hard gate: work never skips ahead. Most merges stop at **Verification** — the **Release** stage fires only when a milestone gate is being closed.

---

## 3. Merge Policy

1. **Only the Lead merges.** No exceptions, including the Lead's own PRs (which still pass review first).
2. **Squash Merge is the standard** (03 §11). One feature = one commit; the PR title becomes the permanent commit message; rollback is one `git revert`.
3. **Merge order is the Lead's call.** When multiple PRs are approved, the Lead sequences them by dependency and conflict risk (backend/API changes land before the portal PRs that consume them; the regenerated api-client always travels with its endpoint change).
4. **Rebase-then-merge freshness rule:** a PR merges only from a branch rebased on current `main` with green CI on that exact state. If `main` moved after approval, the branch rebases and CI re-runs before merge.
5. **No merge while `main` is broken.** If a previous merge degraded the demo flow, fixing `main` preempts all other merges (CONTRIBUTING rule 5).
6. **Milestone discipline:** work for a future milestone does not merge early, no matter how finished — phase gates are strict (ROADMAP).

---

## 4. Release Checklist

Run by the Lead when closing a milestone (declaring a release):

```
☐ Every milestone task Done per 08 (not "code complete" — Done)
☐ Full CI green on main (GitHub Actions, latest commit)
☐ make ci green on a fresh local checkout
☐ Clean-checkout stack verification:
      make up → alembic upgrade head → scripts/seed.py → run api/portals
☐ Milestone gate demo executed end-to-end and passing
      (the ROADMAP gate text, performed literally — run it, don't assume it;
       verified by a member who didn't build the feature, per CHECKLIST.md)
☐ Coverage thresholds hold (≥80% on the milestone's core module)
☐ CHANGELOG.md: [Unreleased] promoted to a versioned, dated milestone entry
☐ ROADMAP.md: milestone marked DONE with date; next milestone marked CURRENT
☐ SESSION.md / TODO.md updated; PO sign-off recorded
☐ Git tag created on the release commit (e.g. v0.3.0-m2) and pushed
☐ M7+ only: deploy executed; smoke tests pass on the hosted environment
```

A release with any unchecked box is not a release — it is a milestone still in progress.

---

## 5. Post-Merge Verification

After **every** merge (not just releases), the Lead verifies within the same working session:

1. **CI on `main` is green** for the merge commit — a red `main` is an all-hands stop.
2. **The demo flow still works:** the quickest end-to-end probe of the affected area (e.g. after a records merge: boot the API, upload via the seeded admin, list, presign).
3. **Migrations apply cleanly forward** on a migrated database (`alembic upgrade head` is a no-op or applies the new head — never errors).
4. **Generated-contract integrity:** if the merge changed endpoints, the committed `openapi.json`/api-client match a fresh `make api-client` run (zero diff).
5. **Open branches notified:** members with in-flight branches rebase onto the new `main` promptly (03 §10).

The **author** additionally performs their post-merge duties (SOP §13): delete branches, pull `main`, verify integration if asked, close the task.

---

## 6. Rollback Strategy

Squash merges make rollback surgical:

1. **Revert, don't rewrite.** A bad feature is removed with `git revert <squash-sha>` — a new commit on `main` via a normal (expedited) PR. **Never** force-push or reset `main` (03 §3).
2. **Migrations rollback deliberately.** If the reverted feature shipped a migration: on shared/live databases prefer a *new forward migration* that undoes the schema (the downgrade path is the tool for local/dev resets); either way, the schema-touching revert is Lead-only and tested up/down/up.
3. **Generated files follow the revert.** If the reverted change altered the API surface, regenerate the api-client in the same revert PR so the contract never lies.
4. **Decide fast:** if `main`'s demo flow is broken and the fix isn't obvious within the hour, revert first, diagnose on a branch second. A demoable `main` outranks anyone's momentum.
5. **Record it.** The revert PR states what broke, why revert over fix-forward, and links the follow-up task in TODO.

## 7. Hotfix Process

For defects that break a demo-critical flow (or, post-M7, production):

1. **Declare it.** Author or discoverer notifies the Lead immediately; the Lead confirms hotfix status (everything else is a normal `bugfix/*`).
2. **Branch `hotfix/<area>-<symptom>` from current `main`** — same base rule as everything (03 §2).
3. **Minimal diff:** the fix plus a regression test. No cleanups, no opportunistic improvements.
4. **Same pipeline, maximum priority.** Review is never skipped — it is expedited: the Lead reviews immediately, target turnaround measured in hours; author on standby for comments.
5. **Squash merge, immediate post-merge verification (§5)**, branch deleted.
6. **Post-hotfix accounting:** TODO/SESSION note what escaped, which test gap allowed it, and the follow-up that closes that gap. A hotfix without a lesson is scheduled to recur.

---

## 8. Best Practices

- **Merge small, merge often.** A steady stream of small squash commits keeps every rebase cheap and every revert precise.
- **Sequence API before UI.** Backend/API PRs (with regenerated client) land first; portal PRs consume them after a rebase — never the other way around.
- **Run the gate demo literally.** Milestone gates are performed, step by step, from a clean checkout — the gate text is a script, not a vibe (CHECKLIST.md: *run the demo flow, don't assume*).
- **Tag every milestone.** Tags are the only cheap time machine — `git checkout v0.3.0-m2` must always reproduce the M2 demo.
- **Keep CHANGELOG.md honest and current.** It is written per-merge under `[Unreleased]` and promoted at release — never reconstructed from memory afterwards (we've had to backfill once; not again).
- **Never release on a Friday-equivalent.** Close milestone gates when the team is available to react — a release the PO can't demo-verify immediately is just a merge with a fancy name.
- **The deferred-ops list is part of the release.** While Docker/MinIO/Firebase live-verification items remain open (PO ops tasks), every release notes explicitly which gate criteria were fake-verified versus live-verified — no silent gaps.

---

*Maintained by the Lead Developer. This process gains deployment stages at M7 (ADR-009); the merge policy itself does not change.*
