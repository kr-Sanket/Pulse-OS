# PulseOS — Project Management Handbook

> **Document:** `project-management/01_PROJECT_MANAGEMENT.md`
> **Status:** Active — the entry point and index for the handbook
> **Audience:** everyone, starting with any new contributor's first hour on the project

Welcome. This is the front page of the PulseOS Project Management Handbook — nine documents that define how a three-person team, working with heavy AI assistance on a security-critical healthcare platform, ships production-quality software without stepping on each other.

This page tells you what each document is for, in what order to read them, and how they fit together. It deliberately repeats none of their content.

---

## 1. Purpose

PulseOS is a patient-centric healthcare interoperability platform with production-grade ambitions and a research goal. Its hardest problems are not technical — they are coordination problems: one platform, three portals, strict security invariants, a fixed timeline, and contributors who each own a different slice.

This handbook exists so that coordination is **written down, not negotiated per incident**. It answers, in advance, the questions that otherwise get answered differently every time:

- Who owns this code? *(02)*
- How do branches and merges work? *(03)*
- What is the exact procedure from task to merge? *(04)*
- How is work assigned, proposed, reviewed, finished, and released? *(05–09)*
- What is never up for debate? *(10)*

The handbook complements — never replaces — the technical documentation: architecture lives in [`docs/`](../docs/), decisions in [`.claude/DECISIONS.md`](../.claude/DECISIONS.md), milestones in [`.claude/ROADMAP.md`](../.claude/ROADMAP.md). The handbook governs the *people and process*; those documents govern the *system*.

---

## 2. Handbook Structure

| # | Document | Purpose | Use it when | Primary readers |
|---|---|---|---|---|
| 02 | [Team Responsibilities](02_TEAM_RESPONSIBILITIES.md) | Defines exactly one owner for every area — Lead (platform), Member 1 (Patient Portal), Member 2 (Hospital & Doctor Portals) — plus escalation rules | Before touching any file you're unsure you own; whenever you need something outside your area | Everyone, first |
| 03 | [Branch Strategy](03_BRANCH_STRATEGY.md) | The Git model: protected `main`, short-lived `feature/*` branches, rebase syncing, squash merges | Every time you create, sync, or finish a branch | Everyone |
| 04 | [Development Workflow](04_DEVELOPMENT_WORKFLOW.md) | The SOP — the single lifecycle every change follows from assignment to merged commit | Daily; it *is* the daily loop | Everyone |
| 05 | [Task Assignment Template](05_TASK_ASSIGNMENT_TEMPLATE.md) | The written contract for each task: scope, forbidden files, available APIs, acceptance criteria | Lead: when assigning. Members: when receiving — before the first line of code | Lead writes, members read |
| 06 | [PR Template](06_PR_TEMPLATE.md) | The standard Pull Request description and the author's pre-review checklist | Every time you open a PR | Everyone (authors) |
| 07 | [Code Review Checklist](07_CODE_REVIEW_CHECKLIST.md) | The reviewer's instrument: severity-ordered checks and the approve/reject decision matrix | During every review; authors read it to self-review before requesting one | Lead + Claude (reviewers); authors for self-review |
| 08 | [Definition of Done](08_DEFINITION_OF_DONE.md) | The binary, verifiable standard for "complete" — coding, testing, docs, review, merge | Before claiming any task is finished; when scoping what "finished" will require | Everyone |
| 09 | [Release Process](09_RELEASE_PROCESS.md) | How merged work becomes a verified, tagged, milestone-closing release; rollback and hotfix paths | At every merge (post-merge verification) and every milestone gate | Lead primarily; everyone for hotfix awareness |
| 10 | [Project Rules](10_PROJECT_RULES.md) | The engineering handbook proper: non-negotiable rules across ownership, security, testing, AI usage — and the prohibited-actions blacklist | Read once fully; consult whenever a situation feels like an exception | Everyone |

---

## 3. Reading Order

For a new contributor, read in this order — ownership first, mechanics second, standards third:

```
New contributor
      ↓
02  Team Responsibilities      (learn what is yours — and what is not)
      ↓
03  Branch Strategy            (learn how code moves)
      ↓
04  Development Workflow       (learn the daily loop)
      ↓
05  Task Assignment            (learn how work arrives)
      ↓
10  Project Rules              (learn what is never negotiable)
      ↓
08  Definition of Done         (learn what "finished" means)
      ↓
06  PR Template                (learn how to hand work over)
      ↓
07  Review Checklist           (learn how it will be judged)
      ↓
09  Release Process            (learn how it reaches the world)
```

Total reading time: roughly two hours. Those two hours have already proven cheaper than the alternative — this project once lost a full implementation to a contributor working outside these agreements.

---

## 4. Development Lifecycle

Every change, regardless of size or author, travels this path — each stage owned by one handbook document:

```
        Idea                    (ROADMAP milestone / TODO entry / proposal to the Lead)
          ↓
   Task Assignment              (Lead fills the 05 template; owner confirms scope)
          ↓
     Development                (04 SOP: fresh main → feature branch → owned scope only)
          ↓
       Testing                  (04 §6: full local gates green — make ci)
          ↓
    Pull Request                (06 template; Conventional title; author checklist)
          ↓
       Review                   (07 checklist: Lead + Claude architectural review)
          ↓
      Approval                  (all threads resolved with pushed changes)
          ↓
        Merge                   (09 §3: Lead squash-merges; one feature = one commit)
          ↓
      Release                   (09 §4: milestone gate demo → CHANGELOG + tag)
```

Nothing skips a stage. Most changes stop at **Merge**; the **Release** stage fires when a milestone gate closes.

---

## 5. Contributor Journey — Day 1

What a new (or returning) developer actually does on their first day:

1. **Read this page**, then documents 02 → 03 → 04 (the minimum before touching code). Skim 10.
2. **Read the project context:** [`README.md`](../README.md) (quickstart + status), [`.claude/CLAUDE.md`](../.claude/CLAUDE.md) (the doc map), and the ADRs relevant to your area.
3. **Set up the environment** per the README: clone, `make install`, `make up`, migrate, seed, run your portal or the API — confirm the stack works before writing anything.
4. **Find your name in 02** and walk your owned directories in the repo. Everything outside them is read-only territory for you.
5. **Receive your first task** as a filled-in 05 template from the Lead. Read it, read its listed ADRs, and ask every unclear question *now*.
6. **Run the loop:** `git checkout main && git pull` → `git checkout -b feature/…` → implement → `make ci` → PR per 06.
7. **Expect your first review to be thorough.** The 07 checklist is applied fully; the first PR is where habits are calibrated. Small first task, fast merge, confidence earned.

By the end of Day 1 you should have: a working local stack, a confirmed task, a branch, and — ideally — a small first PR open.

---

## 6. Guiding Philosophy

The principles under everything in this handbook (expanded in 10 §13):

- **One owner per feature.** Every artifact has exactly one accountable person. Shared ownership is no ownership.
- **Architecture first.** The design is decided and ADR-recorded before code exists; code conforms to it, never the reverse.
- **Small PRs.** Small changes get real reviews, cheap rollbacks, and fast merges.
- **Stable `main`.** Always demoable, always releasable — the team's standing promise to itself.
- **Security by default.** Deny-by-default authorization, consent as the choke point, no PHI in logs — engineered as if the synthetic data were real.
- **Documentation is part of development.** A change without its docs, ADR, or session notes is unfinished work, not fast work.
- **AI assists developers but never owns decisions.** All code here is AI-assisted; every line still has a human owner who understands it, tests it, and answers for it. Decisions belong to the Lead and the ADRs — tools implement them.

---

## 7. Document Relationships

How the handbook interlocks — each document feeds the next stage of the lifecycle:

```
                        ┌──────────────────────────────┐
                        │ 01  This page (index)        │
                        └──────────────┬───────────────┘
                                       │ introduces
        ┌──────────────────────────────┼──────────────────────────────┐
        ▼                              ▼                              ▼
┌───────────────┐             ┌───────────────┐              ┌───────────────┐
│ 02 Ownership  │──scopes──▶  │ 05 Task       │──starts──▶   │ 04 Workflow   │
│ (who)         │             │ Assignment    │              │ (SOP)         │
└───────┬───────┘             │ (what)        │              └───────┬───────┘
        │ bounds              └───────────────┘                      │ uses
        ▼                                                            ▼
┌───────────────┐             ┌───────────────┐              ┌───────────────┐
│ 10 Rules      │◀─enforced─  │ 07 Review     │◀──judged──   │ 03 Branches   │
│ (never)       │   via       │ Checklist     │    via       │ + 06 PR       │
└───────────────┘             └───────┬───────┘              └───────────────┘
                                      │ gates
                                      ▼
                              ┌───────────────┐             ┌───────────────┐
                              │ 08 Definition │──closes──▶  │ 09 Release    │
                              │ of Done       │             │ Process       │
                              └───────────────┘             └───────────────┘
```

In words: **02** decides who may do the work; **05** defines the work; **04** (using **03**) produces it; **06** hands it over; **07** judges it against **10**; **08** declares it finished; **09** ships it. Break any link and the chain's guarantees disappear — which is why the documents cross-reference rather than duplicate each other.

Beyond the handbook, three anchors from the technical docs are cited throughout: [`.claude/DECISIONS.md`](../.claude/DECISIONS.md) (ADRs — the decided architecture), [`.claude/ROADMAP.md`](../.claude/ROADMAP.md) (milestones and gates), and [`.claude/CHECKLIST.md`](../.claude/CHECKLIST.md) (the per-PR quality gates the handbook operationalizes).

---

## 8. Maintaining the Handbook

The handbook is a living document set, maintained by the Lead Developer:

- **Changes arrive like any other change:** a `docs/*` branch, a PR, Lead review, squash merge (yes, the handbook obeys its own rules).
- **Anyone may propose** an amendment — in writing, with the failure or friction that motivates it. Rules are added when reality teaches something, and removed almost never.
- **Update triggers:**
  - a process failure occurs that a written rule would have prevented → the rule is added where it belongs (usually 10 §12 or 07 §12);
  - team structure or ownership changes → 02 first, then every document that names owners;
  - the project enters a new phase with new mechanics (e.g. deployment at M7) → 09 gains its deployment stages, 08 tightens its deployment criteria;
  - tooling changes (gates, generators, CI) → 04 §6 and 06/07 checklists synchronize in the same PR.
- **Consistency rule:** terminology (branch names, gate commands, role names, merge policy) must stay identical across all nine documents plus `docs/CONTRIBUTING.md`. A PR that changes a term in one place changes it everywhere.
- **This index is updated last, in the same PR** as any structural change — the front page never advertises a handbook that doesn't exist.

---

*Maintained by the Lead Developer. If you've read this far: welcome aboard — your next stop is [`02_TEAM_RESPONSIBILITIES.md`](02_TEAM_RESPONSIBILITIES.md).*
