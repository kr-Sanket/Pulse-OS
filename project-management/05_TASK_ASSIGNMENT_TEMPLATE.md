# PulseOS — Task Assignment Template

> **Document:** `project-management/05_TASK_ASSIGNMENT_TEMPLATE.md`
> **Status:** Active — used by the Lead Developer for every implementation task
> **Related:** [`02_TEAM_RESPONSIBILITIES.md`](02_TEAM_RESPONSIBILITIES.md) · [`03_BRANCH_STRATEGY.md`](03_BRANCH_STRATEGY.md) · [`04_DEVELOPMENT_WORKFLOW.md`](04_DEVELOPMENT_WORKFLOW.md)

---

## 1. Purpose

Every implementation task in PulseOS is assigned in writing, using the template in §3, before any code is written.

A written assignment exists to make three things impossible:

- **Ambiguity** — the developer knows exactly what to build, against which APIs, with which acceptance criteria, before starting. "I assumed…" is a failure of the *assignment*, and this template is how the Lead prevents it.
- **Scope creep** — the assignment states what is in scope *and what is not*, down to the file level. Anything not listed is not part of the task (SOP §3: never assume missing requirements).
- **Ownership collisions** — `Files Allowed` / `Files Forbidden` make the ownership boundary (`02_TEAM_RESPONSIBILITIES.md`) concrete per task, so a scope violation is visible before the first commit, not at PR review.

The filled-in template is the contract for the task. The PR is reviewed against it.

---

## 2. Assignment Workflow

```
Task Planning            (Lead: slice the milestone into ownable tasks — ROADMAP/TODO)
      ↓
Task Assignment          (Lead: fill in the template §3, deliver to the owner)
      ↓
Developer Review         (Owner: read the task, the listed ADRs, and the listed docs)
      ↓
Questions                (Owner: ask everything unclear NOW — before any code)
      ↓
Approval                 (Lead: answers recorded in the task's Notes; owner confirms scope)
      ↓
Development Starts       (Owner: SOP §4 — pull main, create the named branch)
```

Rules of the workflow:

- A task is **not started** until the owner has confirmed they understand the scope. Silence is not confirmation.
- Questions and their answers are appended to the task's **Notes** section — the task document stays the single source of truth.
- If planning reveals the task needs work outside the owner's domain (an API, a migration, a shared component), the Lead splits it: the platform part becomes a Lead task and a **Dependency** of this one.

---

## 3. Task Assignment Template

Copy everything between the markers. Fill every field — write `None` rather than deleting a row; an empty field is an ambiguity.

```markdown
<!-- ==================== TASK ASSIGNMENT ==================== -->

# Task: <TASK NAME>

| Field | Value |
|---|---|
| **Task Name** | <short, specific name> |
| **Assigned To** | <Lead / Member 1 / Member 2> |
| **Milestone** | <M2 / M3 / … — per .claude/ROADMAP.md> |
| **Branch Name** | <feature/…, bugfix/…, docs/… — per 03 §2> |
| **Target PR** | <one PR; Conventional-Commit title it should carry> |
| **Estimated Effort** | <S: ≤1 day · M: 2–3 days · L: split it — see §7> |

## Goal
<One or two sentences: the outcome this task produces, stated from the user's or
system's point of view. If the goal needs a paragraph, the task is too big.>

## Background
<Why this task exists now: the milestone context, what already exists that this
builds on, links to the relevant sections of ROADMAP / DOMAIN_MODEL / prior PRs.>

## Scope
<Numbered list of exactly what to implement. Concrete and testable — screens,
endpoints consumed, states handled, edge cases included.>
1. …
2. …

## Out of Scope
<Numbered list of the nearest things NOT to build — the temptations. Name them
explicitly so "while I was here" has no cover.>
1. …
2. …

## Deliverables
<The artifacts the PR must contain: pages/components/tests/screenshots/docs.>
- …

## Files Allowed
<Directories/files the branch may create or modify. Everything else is forbidden
by default.>
- …

## Files Forbidden
<High-risk paths worth naming explicitly even though the default already covers
them (backend/, alembic/, generated client, ADRs, other portals…).>
- …

## Dependencies
<What must be merged/available before this task can start or finish: other tasks,
Lead-provided APIs, seed data, designs. "None" if truly independent.>
- …

## APIs Available
<The exact backend endpoints this task may consume, as they exist on main today —
method + path, with a pointer to the generated client types. The task may use
NOTHING that is not on this list.>
- …

## Database Changes Allowed?
**NO** for Members 1 and 2, always. For Lead tasks: <NO / YES — migration NNNN,
tables listed>.

## ADRs to Read
<The ADR numbers whose decisions constrain this task, with one-line reasons.>
- ADR-0xx — <why it matters here>

## Acceptance Criteria
<Checkable statements. Each one is verifiable by the reviewer without asking
the author anything.>
- [ ] …
- [ ] …

## Required Tests
<The tests the PR must add — including the negative cases. Be specific enough
that their absence is objective.>
- …

## Documentation Updates
<Which docs this task must touch (or "None"). Per SOP §10 row 7.>
- …

## Definition of Done
- [ ] All Acceptance Criteria pass
- [ ] All Required Tests written and green
- [ ] Full local gates green (`make ci`) — SOP §6
- [ ] No files outside **Files Allowed** touched
- [ ] Documentation Updates completed
- [ ] PR opened with the Target PR title; description states scope
- [ ] `.claude/CHECKLIST.md` Definition of Done satisfied

## Notes
<Anything else: known pitfalls, design references, answers to questions asked
during Developer Review (append here, dated).>

<!-- ================== END TASK ASSIGNMENT =================== -->
```

---

## 4. Scope Rules

These apply to every task, are implied by every assignment, and repeat here because they are the rules most often broken:

1. **Implement ONLY the assigned scope.** The `Scope` list is exhaustive. If something seems missing, it is a question for the Lead (§2), not an addition to the branch.
2. **Never anticipate future milestones.** Do not build "hooks for M3," placeholder screens for unshipped APIs, or columns for future features. Phase gates are strict (`.claude/ROADMAP.md`); future work gets its own assignment when its milestone starts.
3. **Never redesign architecture.** Module boundaries, layering, and patterns are fixed by ADRs. A task is never a license to restructure — architectural proposals go to the Lead as ADR drafts (02 §5).
4. **Never create extra abstractions.** No wrappers, base classes, generics, or "reusable" utilities beyond what the scope demands. The boring solution is the house style; the sanctioned abstractions (provider ports) already exist.
5. **Never modify forbidden files.** `Files Forbidden` plus everything outside `Files Allowed` is untouchable — including formatting, imports, and comments. A PR that touches them is closed unreviewed (SOP §10, row 1).

---

## 5. Good Assignment Example

```markdown
# Task: Hospital Portal — Record Upload Page

| Field | Value |
|---|---|
| **Task Name** | Hospital Portal — Record Upload Page |
| **Assigned To** | Member 2 |
| **Milestone** | M2 — Backend Core (frontend consumption) |
| **Branch Name** | feature/hospital-record-upload-ui |
| **Target PR** | feat(hospital): add record upload page |
| **Estimated Effort** | M (2–3 days) |

## Goal
A hospital admin can upload one medical document against a patient's Health ID
from the Hospital Portal and see confirmation of the created record.

## Background
The M2 backend shipped `POST /api/v1/records` (multipart) and the reference
vocabulary endpoint; the api-client was regenerated in commit 113d815. This is
the first Hospital Portal page beyond the shell — it proves the M2 gate flow in
the browser. Seeded admins exist for HID-0001..3 (see records/seed.py).

## Scope
1. Upload form: file picker (PDF/JPEG/PNG only), patientHealthId input with
   client-side ADR-012 format hint, category select populated from
   GET /record-categories, dateOfService date picker (no future dates),
   optional description.
2. Submit via the generated client (`POST /records` multipart); disable the
   form while in flight.
3. Handle and display: 201 success (show returned record metadata), 422 field
   errors (map problem+json detail to the form), 413 too large, 415 bad type,
   409 hospital unverified, 503 storage down.
4. Route `/records/upload` behind the existing auth guard; nav entry.

## Out of Scope
1. Record listing/search pages (separate task).
2. Bulk upload (M4).
3. Doctor Portal anything.
4. Any change to upload validation rules — display what the API returns.

## Deliverables
- Upload page + form components under web/apps/hospital/src/
- Vitest coverage per Required Tests
- Two demo screenshots (empty form, success state) in the PR description

## Files Allowed
- web/apps/hospital/src/** (new pages/components/tests)

## Files Forbidden
- backend/**, web/packages/api-client/**, web/packages/config/**,
  web/apps/patient/**, web/apps/doctor/**, .claude/**, infra/**

## Dependencies
- None — all required APIs are on main.

## APIs Available
- POST /api/v1/records (multipart: file, categoryCode, dateOfService,
  description?, patientHealthId) — types in @pulseos/api-client
- GET /api/v1/record-categories

## Database Changes Allowed?
**NO.**

## ADRs to Read
- ADR-003 — generated api-client is the only HTTP path
- ADR-012 — Health ID format (for the input hint; validation stays server-side)
- ADR-015 — why an unverified hospital gets 409 on upload

## Acceptance Criteria
- [ ] Admin (seeded HID-0001 admin) can upload a PDF and sees the created
      record's category, filename, and date reflected back
- [ ] Non-PDF/JPEG/PNG file is rejected client-side before any request
- [ ] Each API failure mode in Scope #3 renders a distinct, readable message
- [ ] No direct fetch() anywhere in the diff

## Required Tests
- Form validation: missing required fields, bad file type, future date
- Submit flow with mocked client: success path renders confirmation
- Error mapping: 422 problem+json details land on the right fields; 413/415/
  409/503 render their messages

## Documentation Updates
- Hospital Portal screen inventory (Member 2's docs) — add the upload page

## Definition of Done
- [ ] (standard block from the template)

## Notes
- Max upload size is a backend setting (15 MiB default); read the limit from
  the 413 response rather than hardcoding it client-side.
```

**Why this is a good assignment:** the goal is one sentence; every scope item is testable; the nearest temptations (listing page, bulk upload, doctor portal) are explicitly fenced out; the API surface is enumerated exactly; file boundaries are unambiguous; acceptance criteria are checkable by a reviewer without a conversation.

---

## 6. Bad Assignment Example

```markdown
# Task: Hospital stuff

Assigned To: Member 2

Build the hospital side of the app. Admins should be able to manage the
hospital and upload records and whatever else they need. Add any missing
backend endpoints if something isn't there yet. Try to make it look good and
reuse components where possible. Should be quick.
```

**Why this fails — every defect this template exists to prevent:**

| Defect | Consequence |
|---|---|
| No milestone, branch, or PR target | Untraceable; branch naming improvised |
| "and whatever else they need" | Unbounded scope — the developer becomes the product owner |
| "Add any missing backend endpoints" | Instructs an ownership violation (backend is Lead-only, 02 §3) — this exact pattern produced the discarded parallel implementation |
| No Files Allowed/Forbidden | Scope violations discovered only at PR review |
| No APIs Available list | Developer guesses the contract or invents one |
| No acceptance criteria or required tests | "Done" is a feeling; review becomes negotiation |
| "Should be quick" | An estimate is not a sizing; pressure substitutes for scoping |
| No ADRs, no out-of-scope, no dependencies | The developer must assume — and SOP §3 forbids assuming |

---

## 7. Best Practices

**For the Lead (writing assignments):**

- **Size tasks S or M.** Anything estimated L is split before assignment — two small tasks review and merge faster than one large one, and the second can be re-scoped after the first lands.
- **Write `Out of Scope` as the list of temptations.** The best fence names the specific adjacent things the developer will be tempted to build.
- **Enumerate APIs from `main`, not from plans.** If an endpoint isn't merged, it isn't "available" — it's a Dependency on a Lead task.
- **Make acceptance criteria reviewer-checkable.** Each criterion should be verifiable from the PR alone: a behavior, a rendered state, a test's existence — never "works well."
- **One task, one branch, one PR.** If the template needs two branch names, it's two tasks.

**For the assignee (receiving assignments):**

- **Read everything before estimating agreement** — including the listed ADRs. Confirmation of scope is a commitment.
- **Ask questions at assignment time**, not mid-implementation. Every answer goes into Notes so it binds.
- **Treat `Files Allowed` as a whitelist**, not a suggestion. If your editor touched a file outside it — even formatting — revert before committing.
- **When blocked by a missing dependency, stop and report** — don't build a stand-in (SOP §5.8).
- **Deliver exactly the Deliverables.** Extra artifacts are scope creep dressed as generosity; missing ones are an unfinished task.

---

*Maintained by the Lead Developer. The template in §3 is copied into each new task; changes to the template itself arrive via a Lead-approved `docs/*` PR.*
