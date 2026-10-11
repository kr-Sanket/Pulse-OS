# PulseOS — Team Responsibilities & Ownership

> **Document:** `project-management/02_TEAM_RESPONSIBILITIES.md`
> **Status:** Active — binding for all contributors
> **Applies to:** the entire PulseOS repository (`backend/`, `web/`, `mobile/`, `contracts/`, `infra/`, `scripts/`, `docs/`, `.claude/`)
> **Related:** [`docs/CONTRIBUTING.md`](../docs/CONTRIBUTING.md) · [`.claude/CHECKLIST.md`](../.claude/CHECKLIST.md) · [`.claude/ROADMAP.md`](../.claude/ROADMAP.md) · [`.claude/DECISIONS.md`](../.claude/DECISIONS.md)

---

## 1. Purpose

Every part of PulseOS has **exactly one owner**. This document defines who that owner is, for every area of the system, so that no decision, file, or feature is ever ambiguous.

Why single ownership is non-negotiable:

- **Accountability.** When a feature works, one person made it work. When it breaks, one person is responsible for fixing it. Shared ownership means no ownership.
- **No duplicate work.** Two people implementing the same concept independently produces two incompatible versions of the truth (two models, two migrations, two APIs) and an integration failure. This has already happened once in this project; this document exists so it never happens again.
- **Protected invariants.** PulseOS carries security-critical invariants (consent enforcement, deny-by-default authorization, append-only audit). These survive only if the code that implements them has a single, consistent author and reviewer.
- **Merge stability.** `main` is always demoable. That is only achievable when changes flow through one integration point with one final decision-maker.

**The rule in one sentence:** if it is not in your "Owns" list below, you do not write it, change it, or redesign it — you ask its owner.

---

## 2. Team Structure

| Role | Ownership Domain |
|---|---|
| **Lead Developer** | Platform & Architecture Owner — everything backend, infrastructure, and cross-cutting |
| **Member 1** | Patient Experience Owner — the Patient Portal frontend |
| **Member 2** | Hospital & Doctor Experience Owner — the Hospital Portal and Doctor Portal frontends |

Ownership boundaries follow the system's architecture: **one owner for the platform, one owner per user-facing experience.** Frontend owners build exclusively against backend APIs that the Lead has already implemented, exposed through the generated API client.

---

## 3. Detailed Responsibilities

### 3.1 Lead Developer — Platform & Architecture Owner

#### Primary Responsibility
Design, implement, and protect the entire PulseOS platform: architecture, backend, data, security, infrastructure, and the integration of all contributions into a stable, releasable `main`.

#### Owns
- **Architecture** — system design, module boundaries, all ADRs (`.claude/DECISIONS.md`)
- **Backend core** — `backend/app/core/` (config, DB, logging, middleware, errors, health, queue)
- **Database** — schema design, all models, all Alembic migrations (`backend/alembic/`)
- **Authentication & authorization** — the `auth` module, Firebase integration, role claims, role gates (ADR-011, ADR-013)
- **Health ID generation** — ADR-012 implementation (`patients/health_id.py`)
- **Medical Records architecture** — the `records` module: models, storage port, upload/read/download services and endpoints
- **Consent** — the `consent` module (M3): enforcement choke point, grants, decisions
- **Audit** — append-only audit log, `AuditAnchor` interface
- **Blockchain** — Solidity contracts, Polygon anchoring, reconciliation (ADR-004, M6)
- **AI** — the `ai` module: OCR, RAG, LLM integration, redaction layer (ADR-007, M5)
- **Shared libraries & core utilities** — `backend/app/shared/`, `web/packages/api-client/`, `web/packages/config/`
- **Workers** — `backend/app/workers/`, arq, Redis queue (ADR-008, ADR-014)
- **Infrastructure** — Redis, MinIO, Docker, `infra/docker-compose.yml`
- **CI/CD** — GitHub Actions workflows, quality gates
- **OpenAPI & API client generation** — the spec, `scripts/export_openapi.py`, `make api-client`
- **Project integration & release management** — merge order, version tags, `CHANGELOG.md`
- **PR reviews and final merge decisions** — every PR, without exception

#### Daily Responsibilities
- Design architecture before implementation; record every non-obvious decision as an ADR
- Approve or reject all technical decisions before they are coded
- Review every PR against `.claude/CHECKLIST.md` (module isolation and consent enforcement first)
- Maintain code quality: ruff, mypy strict, pytest on backend; hold the ≥80% coverage bar on core modules
- Maintain the roadmap and phase gates (`.claude/ROADMAP.md`); enforce "no next phase before the gate passes"
- Resolve all merge conflicts; keep `main` stable and demoable at all times
- Own final production integration and deployment

#### Deliverables
- All backend milestones (M2 records core, M3 consent, M5 AI, M6 blockchain, M7 hardening/deploy)
- Every Alembic migration, reversible and tested
- The OpenAPI spec and regenerated API client after every endpoint change
- ADRs, roadmap updates, session/handoff notes, release notes

#### Technologies Responsible For
Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL, Redis, arq, boto3/MinIO, Firebase Admin SDK, Ollama (local, Qwen3:8B — ADR-028), pycryptodome (Keccak-256), Docker, *planned/undecided:* OCR, pgvector, contract toolchain and chain client (see docs/TECH_STACK.md), GitHub Actions, OpenAPI toolchain (openapi-typescript, openapi-fetch).

#### Testing Responsibility
All backend testing: unit, integration, migration, contract (OpenAPI), and security/negative-authorization tests. Every consent- or records-touching endpoint ships with negative tests (wrong role, wrong patient, revoked grant).

#### Documentation Responsibility
`docs/` architecture set, `.claude/` (ADRs, ROADMAP, SESSION, TODO, CHECKLIST), `CHANGELOG.md`, `.env.example`, API docstrings (purpose, roles, consent requirement, failure modes on every endpoint).

#### Code Review Responsibility
Reviews **every** PR from Members 1 and 2. Review order per `docs/CONTRIBUTING.md`: (1) module-isolation / consent-enforcement violations — instant block; (2) presence of negative-authz tests; (3) simplest-thing-that-works; (4) style. Holds the only merge authority.

#### What They MUST NOT Delegate
- Architecture and ADRs
- Database design and migrations
- Consent (domain logic and enforcement)
- AI (pipeline, redaction, provider integration)
- Blockchain (contracts, anchoring, reconciliation)
- Authentication and authorization
- Infrastructure (Docker, CI/CD, Redis, MinIO)

These areas carry the project's security invariants and research claims. They are implemented by the Lead personally, regardless of schedule pressure.

---

### 3.2 Member 1 — Patient Experience Owner

#### Primary Responsibility
Design, build, and test the **entire Patient Portal frontend** (`web/apps/patient/`) as a polished, accessible, demo-ready experience — consuming only APIs the Lead has already shipped.

#### Owns
- `web/apps/patient/` in full:
  - Login UI and Registration UI (Firebase sign-in flow, transparent registration)
  - Dashboard UI
  - Profile UI (Health ID display, health profile)
  - Medical Record pages (locker, record list, record detail, upload UI for locker files)
  - Consent pages — **frontend only** (consent inbox, approve/reject/revoke screens, audit log view; the consent *backend* is the Lead's)
  - Notifications UI
  - Settings
  - Navigation, routing, protected routes
  - Forms and client-side validation
  - Responsive design and accessibility (keyboard navigation, contrast, semantics)
  - All Patient Portal frontend tests

#### Daily Responsibilities
- Implement React components and pages within `web/apps/patient/` only
- Integrate **exclusively** through the generated `@pulseos/api-client` — **never a direct `fetch()`**, never a hand-written HTTP call
- Build only against backend APIs that already exist on `main`; if an API is missing, request it from the Lead (see §6) — do not stub your own backend
- Improve UX iteratively; keep every flow demo-ready
- Write and maintain frontend tests alongside every feature
- Prepare demo screenshots for reviews and milestone gates

#### Deliverables
- Complete Patient Portal for each milestone's demo flows (login → profile → records → consent inbox → audit log, as milestones unlock)
- Passing vitest suites and a green `pnpm build` for the patient app at all times
- Demo screenshots per milestone

#### Technologies Responsible For
React, TypeScript (strict), Vite, Tailwind CSS, react-router, Firebase Web SDK (client-side auth only), vitest + testing-library, the generated `@pulseos/api-client` (as a consumer).

#### Testing Responsibility
All Patient Portal frontend tests: component tests, flow logic tests (e.g. registration/consent flows), accessibility checks. Every page ships with tests; `pnpm test` and `pnpm typecheck` green before any PR.

#### Documentation Responsibility
Patient Portal usage notes, screen inventory, and demo scripts for patient journeys. Update frontend-relevant sections of docs when patient-facing behavior changes.

#### Code Review Responsibility
None as approver. May give informal feedback on Member 2's frontend PRs; approval and merge remain with the Lead.

#### What They MUST NOT Modify
- Anything under `backend/` — including backend code of any kind
- Database schema or `backend/alembic/` (migrations)
- Authentication backend (`auth` module, Firebase Admin, claims)
- Health ID logic
- Consent backend, Records backend
- AI, Blockchain, Workers
- Infrastructure (`infra/`, Docker, CI workflows)
- The OpenAPI spec, `scripts/export_openapi.py`, API client generation, or the generated client source (`web/packages/api-client/`)

---

### 3.3 Member 2 — Hospital & Doctor Experience Owner

#### Primary Responsibility
Design, build, and test the **entire Hospital Portal frontend** (`web/apps/hospital/`) and the **entire Doctor Portal frontend** (`web/apps/doctor/`) — consuming only APIs the Lead has already shipped.

#### Owns
- `web/apps/hospital/` and `web/apps/doctor/` in full:
  - Hospital Dashboard
  - Doctor Dashboard
  - Doctor Management UI (roster, activate/deactivate)
  - Hospital Profile UI
  - Record Upload UI (upload against a Health ID)
  - Record Search UI
  - Record Listing UI
  - Tables, filters, and cursor pagination UI
  - Responsive design and accessibility
  - All Hospital and Doctor Portal frontend tests

#### Daily Responsibilities
- Implement React UI within `web/apps/hospital/` and `web/apps/doctor/` only
- Integrate **exclusively** through the generated `@pulseos/api-client` — **never a direct `fetch()`**
- Build only against backend APIs that already exist on `main`; missing APIs are requested from the Lead (see §6) — never self-implemented
- Test complete workflows end-to-end in the browser (e.g. admin login → upload record → see it listed)
- Write and maintain frontend tests alongside every feature
- Prepare demo screenshots for reviews and milestone gates

#### Deliverables
- Complete Hospital and Doctor Portals for each milestone's demo flows (M2: admin upload + record listing + doctor management; M3: doctor search + access-request flows, as milestones unlock)
- Passing vitest suites and green `pnpm build` for both apps at all times
- Demo screenshots per milestone

#### Technologies Responsible For
React, TypeScript (strict), Vite, Tailwind CSS, react-router, Firebase Web SDK (client-side auth only), vitest + testing-library, the generated `@pulseos/api-client` (as a consumer).

#### Testing Responsibility
All Hospital and Doctor Portal frontend tests: component tests, workflow tests (upload, search, listing, pagination, doctor management), accessibility checks. `pnpm test` and `pnpm typecheck` green before any PR.

#### Documentation Responsibility
Hospital/Doctor Portal usage notes, screen inventory, and demo scripts for hospital and doctor journeys.

#### Code Review Responsibility
None as approver. May give informal feedback on Member 1's frontend PRs; approval and merge remain with the Lead.

#### What They MUST NOT Modify
- Anything under `backend/` — including backend code of any kind
- Database schema or `backend/alembic/` (migrations)
- Authentication (backend or claim logic)
- Consent, AI, Blockchain, Workers
- Infrastructure (`infra/`, Docker, CI workflows)
- Shared libraries and core utilities (`backend/app/shared/`, `backend/app/core/`, `web/packages/ui` internals without Lead approval, `web/packages/config/`)
- The OpenAPI spec or the generated API client (`web/packages/api-client/`)
- Architecture and ADRs (`.claude/DECISIONS.md`)

---

## 4. Responsibility Matrix

**Legend:** **O** = Owner (sole authority) · **C** = Contributor (executes within owner-set boundaries) · — = no access without escalation

| Area | Lead | Member 1 | Member 2 |
|---|:---:|:---:|:---:|
| Architecture & ADRs | **O** | — | — |
| Database schema & Alembic migrations | **O** | — | — |
| Backend core (`app/core/`) & shared libraries | **O** | — | — |
| Authentication & authorization (Firebase, roles) | **O** | — | — |
| Health ID generation | **O** | — | — |
| Medical Records backend | **O** | — | — |
| Consent backend & audit log | **O** | — | — |
| AI (OCR / RAG / LLM) | **O** | — | — |
| Blockchain (contracts, anchoring) | **O** | — | — |
| Workers, Redis, MinIO | **O** | — | — |
| Infrastructure, Docker, CI/CD | **O** | — | — |
| OpenAPI spec & API client generation | **O** | — | — |
| Patient Portal (`web/apps/patient/`) | — | **O** | — |
| Hospital Portal (`web/apps/hospital/`) | — | — | **O** |
| Doctor Portal (`web/apps/doctor/`) | — | — | **O** |
| Consent UI (patient-side screens) | — | **O** | — |
| Record Upload / Search / Listing UI (hospital & doctor side) | — | — | **O** |
| Backend testing | **O** | — | — |
| UI testing | — | **O** (patient) | **O** (hospital, doctor) |
| PR reviews (approval) | **O** | — | — |
| Merge to `main` | **O** | — | — |
| Release management | **O** | — | — |
| Documentation | **O** (architecture, backend, process) | **C** (patient UX docs) | **C** (hospital/doctor UX docs) |
| Demo preparation | **C** (backend + data) | **C** (patient journeys) | **C** (hospital/doctor journeys) |

Every row has exactly one **O** per artifact. If an area you need to touch is not in this table, it belongs to the Lead by default — ask first.

---

## 5. Collaboration Rules

1. **One feature = one owner.** A feature is never split across owners; its owner delivers it end to end within their domain.
2. **Never implement another member's responsibility.** Not as a favor, not as a prototype, not "just to unblock myself." Parallel implementations of the same concept are treated as defects, not contributions.
3. **If blocked, ask the owner.** A missing API, component, or fixture is a request to its owner — never a license to build it yourself.
4. **Never redesign architecture.** Architecture changes are proposed to the Lead as ADR drafts and implemented only after approval.
5. **Never change ADRs.** ADRs are appended or superseded by the Lead only. Existing ADRs are never edited or deleted.
6. **Never modify the database schema unless assigned.** All schema changes are Lead-authored Alembic migrations. No exceptions, including "tiny" columns.
7. **Always communicate before expanding scope.** If a task grows beyond its assignment, stop and confirm with the Lead before writing the extra code.
8. **Frontend talks to the backend through the generated API client only.** A direct `fetch()` in an app is a review-blocking defect.
9. **Branch from current `main`, always.** Working from a stale base creates conflicting duplicates; pull before you branch, rebase before you open a PR.
10. **`main` is sacred.** No direct pushes; every change arrives via a Lead-approved PR with green CI.

---

## 6. Escalation Rules

Members **must contact the Lead and receive explicit approval before proceeding** when any of the following is true. Do not start the work while waiting.

| Situation | What to do |
|---|---|
| You need a **new database table, column, or index** | Describe the data need; the Lead designs the schema and writes the migration |
| You need a **migration** of any kind | Never write one — request it |
| You need an **API change** (new endpoint, new field, changed response shape) | File the request with the exact screen/flow that needs it; the Lead implements and regenerates the API client |
| You believe a **new architecture or pattern** is needed | Propose it in writing; the Lead decides and records an ADR if accepted |
| You want to add a **new dependency** (npm or Python, including dev-deps) | Name the package, license, and reason; wait for approval before `pnpm add` / `pip install` |
| You think an **ADR is wrong or outdated** | Raise it with rationale; only the Lead supersedes ADRs |
| You need a **shared component modified** (`web/packages/ui`, shared config) | Request the change; the Lead approves the interface before any edit |
| Your work **touches another member's files** for any reason | Stop; coordinate through the Lead |
| You found a **security concern** (authz gap, data exposure, secret in code) | Report to the Lead immediately — this escalation is mandatory and blocking |

**Rule of thumb:** if the change would be visible outside your owned directories, it requires the Lead's sign-off first.

---

## 7. Expected Workflow

Every task, regardless of size, follows this lifecycle:

```
Task Assigned (by the Lead, from ROADMAP/TODO)
        ↓
Pull latest main                     (never start from a stale base)
        ↓
Create feature branch                (feat/<area>-<slug> per CONTRIBUTING.md)
        ↓
Implement ONLY the assigned scope    (escalate anything beyond it — §6)
        ↓
Test                                 (your full local gate: lint, typecheck, tests, build)
        ↓
Open PR                              (one logical change; Conventional Commit title;
                                      CHECKLIST.md satisfied; description states scope)
        ↓
Lead Review                          (isolation/consent rules → tests → simplicity → style)
        ↓
Fix review comments                  (push to the same branch; re-request review)
        ↓
Merge                                (Lead squash-merges; main stays demoable)
```

Non-negotiables inside this loop:

- **No PR without green local gates.** CI confirms; it does not discover.
- **No scope smuggling.** A PR containing files outside the author's owned directories is rejected without further review.
- **No long-lived branches.** Small PRs, merged fast; rebase on `main` if it moves under you.
- **Review turnaround target: 24 hours** (per `docs/CONTRIBUTING.md`); authors address comments with the same urgency.

---

*Maintained by the Lead Developer. Changes to this document follow the same rule as everything else: proposed by anyone, approved and merged by the Lead.*
