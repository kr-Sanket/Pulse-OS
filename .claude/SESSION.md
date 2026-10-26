# SESSION.md — Session Log & Handoff Notes

> Newest entry first. Every Claude session appends an entry before ending.
> Format: date, what was done, decisions made, exact next step.

---

## Session 022 — 2026-10-26 · ← CURRENT STATE

**Branch:** `main`. Committed **locally, not pushed** (PO-approved split) as three commits on
`3343e03`: `c2a580f` (ADR-034), `e3c477a` (ADR-035) and the demo/AI/handoff commit after them. No push, merge, PR or deployment. Brief: PO "final feature implementation" request of 2026-10-26, which explicitly
asked for public-testnet anchoring — recorded as proposed ADR-035 pending formal acceptance.

### Work
- **ADR-034 hospital lifecycle** (pre-existing uncommitted Slices 1–3, reviewed and finished):
  fixed stale identity-map read under `FOR UPDATE` (`records/repository.py`, `populate_existing`),
  doctor app badge map for REJECTED/SUSPENDED (tsc/build were failing), admin history panel
  error/staleness. New PostgreSQL tests (real audit-insert rollback, lock blocking, concurrent
  identical transitions, stale row) and an HTTP test that suspension keeps consent/access but
  blocks upload/lookup/registration. ADR-034 text added to DECISIONS.md (Proposed).
- **ADR-035 public-testnet anchoring (M6.4):** `contracts/` (Foundry, `AuditCommitmentRegistry`,
  10 tests incl. ADR-027 pinned vectors); `consent/chain.py` (port + JSON-RPC adapter, chain-id
  allow-list 80002/11155111/31337, EIP-55 normalisation, code-only errors); `consent/
  chain_anchor_service.py` (retry-safe submit, refresh with receipt-event + confirmations +
  contract-state check, on-demand verification); `AuditBatchAnchor` + migration **0011** (head);
  CLI `anchor`/`anchor-refresh` (guarded like `seal`) and `verify-chain`; read-only
  `GET /api/v1/audit-batches/{n}/anchor`; patient proof dialog "Public blockchain anchoring"
  section; `eth-account` dependency; `.env.example`; CI `contracts` job; OpenAPI/client regenerated.
  Security fix found on the way: `httpx` logs full request URLs at INFO (RPC URLs embed keys) —
  pinned `httpx`/`httpcore` to WARNING.
- **Workflows C/D:** `tests/test_demo_sharing_workflow.py`, `tests/test_demo_ai_workflow.py`
  (whole sequences over HTTP); AI panels now label an uncited generated answer "Answer without
  citations" instead of "no evidence". `docs/DEMO_GUIDE.md` written.

### Quality gates (2026-10-26, local working tree — not CI)
| Gate | Result |
|---|---|
| backend pytest + scratch PostgreSQL (127.0.0.1:55432) + anvil EVM | **1475 passed, 0 skipped** |
| backend pytest default | **1436 passed, 39 skipped** (3 consecutive runs); one earlier run had `test_m3_gate::test_the_four_buckets_are_independent_of_one_another` fail once — pre-existing real-clock fixed-window flake, passes in isolation |
| ruff check / format, mypy strict | clean (189 files) |
| contracts `forge fmt --check` / `forge test` | clean / **10 passed** |
| web lint / format / typecheck | clean |
| web vitest | **727 passed** (api-client 17, ui 35, doctor 160, patient 243, hospital 272) |
| web build | all three apps build |

### Pre-commit reliability gate (same day)
- **Activation vs. suspension race fixed:** activation now re-reads the hospital under
  `FOR SHARE` (`HospitalRepository.get_by_id_for_share`) before touching the doctor; lock order
  "hospital row first" documented in ADR-034 decision 10. PostgreSQL tests cover both
  interleavings, concurrent activations, and the request gate; the two race tests fail against
  the old unlocked read (checked by temporarily reverting it, then restoring byte-identical).
- **Policy adopted:** SUSPENDED/non-VERIFIED hospitals cannot open new consent requests (409,
  before Health-ID resolution — no enumeration); existing grants still read; nothing revoked.
  Service + HTTP tests. Gate: `ClinicianDirectory.hospital_accepts_new_requests` (same lock).
- **Docs:** migration downgrade/recovery section (DATABASE_DESIGN.md), 0010/0011 docstrings,
  ADR-034/035 reconciled with the code (ADR-035 separates local-EVM verification from the
  not-performed public deployment), stale "nothing on-chain"/"no contract" lines corrected.
- **Gates:** backend 1481 passed / 0 skipped (PostgreSQL + anvil), 1438 passed / 43 skipped
  default (×2); ruff, mypy clean; forge 10 passed; web 727 passed; lint/format/typecheck/build
  clean; regenerating the API client produces no diff.

### Product Owner decisions (2026-10-26) and final gate
- **ADR-034 accepted. ADR-035 accepted for design + local implementation only**; public-testnet
  deployment and transaction verification remain pending — no public chain anchor exists.
- **Existence discovery gated:** `RecordService.list_existing_categories` refuses a clinician of
  a non-VERIFIED hospital with the existing `HospitalNotVerifiedError` → 409, before the Health
  ID is resolved (identical for any ID). Granted listing, record reads, AI answers and FHIR
  export under an existing grant are untouched — covered by `test_records_service.py`,
  `test_m3_gate.py`, `test_demo_ai_workflow.py`.
- **Final gates:** backend 1484 passed / 0 skipped (PostgreSQL + anvil), 1441 passed / 43
  skipped default (×2); ruff, mypy clean (189 files); forge 10 passed; web 727 passed;
  lint/format/typecheck/build clean; API client regenerates with no diff.

### Not done / blockers
- **No public-testnet deployment or transaction**: no RPC endpoint, deployer key or test funds
  were available. Never claim one until `verify-chain` reports VERIFIED against a real Amoy tx.
- Commit (suggest two commits: ADR-034 series, ADR-035 series) and run CI.
- No sealing/anchoring scheduler; admin history first page only; records-side 409 wording
  ("not verified yet") also used for SUSPENDED.

### Exact next step
PO pushes the three local commits when ready → check CI (new `contracts` job) → fund a testnet-only key and deploy to Amoy
per `contracts/README.md` → `anchor` a sealed demo batch → record tx hash/explorer link here.

---

## Session 021 — 2026-10-25

**Read this entry alone to know where the project stands.** Everything below it is history.

**Branch:** `main`. Session 021 committed its work as a series on top of `0ea4bac` and pushed it to
`origin/main` together with the four previously unpushed commits (`65b68fe`, `2e05ee4`, `c7e5359`,
`0ea4bac`), with Product Owner approval. CI result for that push is recorded in GitHub Actions, not here (unknown at commit time). CI was last reported green on `d09d721`
(run #17, user-provided evidence).

### Landed since Session 020 (committed, from git history and code)

| Commit | What |
|---|---|
| `d25fb82` | Docs reconciliation |
| `15e0b1c` | Hospital verification records `verified_by_user_id` / `verified_at` (migration **0009**, head) |
| `278bbfc` | `scripts/audit_integrity.py seal` environment safety guard (`--confirm-env`, explicit `PULSEOS_ENVIRONMENT`, host rules) |
| `65b68fe` | Account status (ACTIVE) and Firebase token revocation (`check_revoked=True`) enforced on every authenticated request |
| `2e05ee4` | Consent-gated FHIR R4-shaped export, `GET /api/v1/records/export/fhir` |
| `c7e5359` | Audit API v3: batched-event verification, `GET /audit-logs/{id}/proof`, `GET /audit-batches/{n}` |
| `0ea4bac` | Consent re-checked after AI retrieval/synthesis and after FHIR export reads |

### Session 021 work (committed in the Session 021 series)

Started with a read-only repository audit, then fixed what it verified:

- **Audit integrity — VERIFIED overclaim fixed (security).** List and single-event verification
  reported VERIFIED for a batched v3 event without checking Merkle inclusion; editing an event and
  rewriting both its digest and its member digest stayed VERIFIED there. Now every surface uses one
  rule, `merkle.verify_stored_inclusion` (rebuild the batch from stored members, require positions
  `0..n-1`, the leaf at the index, the stored root, and a valid path). A member whose batch row is
  missing is `ANCHOR_ALTERED`. Page verification stays at 3 queries
  (`AuditBatchRepository.members_sharing_batch_with`). Files: `consent/merkle.py`,
  `anchor_service.py`, `batch_service.py`, `repository.py`.
- **`/audit-logs/{id}/proof` no longer 500s** on tampered membership (duplicate/malformed digests,
  gaps): returns `ANCHOR_ALTERED`, `isProofValid: false`, `proof: null` (schema now nullable).
- **AI answer auditing:** no live grant ⇒ `ACCESS_DENIED` (was: unaudited 200); answer discarded
  after a mid-generation revocation ⇒ `ACCESS_DENIED` (was: unaudited); the post-synthesis check
  now fails closed on an unmappable evidence category (`ai/query.py`).
- **`GET /audit-batches/{n}`:** access policy kept (any authenticated role — attestation material,
  no PHI) and documented; added rate-limit bucket `audit_batch_verify` 30/60 s (`core/ratelimit.py`)
  — accepted by the PO (2026-10-25).
- **SEC-01 review:** no backend defects found. Frontend: doctor, hospital and patient bootstraps
  treated the suspended 403 as "unregistered" (onboarding / auto-register). Now detected via
  `@pulseos/ui` `isAccountSuspended` (matches the API detail "Account is suspended.") and shown as
  a suspension message; no token refresh, no registration attempt.
- **OpenAPI + client regenerated** (`scripts/generate-api-client.sh`): 42 operations under
  `/api/v1` (+ `/health`, `/ready`). Exposed a missing `RECORD_EXPORTED` label in both audit
  timelines — added.
- **Patient FHIR export UI:** "Export FHIR (JSON)" on Medical Records and Settings → Your Data
  (replaces the dead "Export Data" button); saves the response body unchanged as
  `pulseos-fhir-export-YYYY-MM-DD.json`; in-flight guard, error/success states. "Delete Account"
  now renders disabled ("not available") instead of a dead button.
- **Patient audit integrity UI:** per-entry badge from the API verdict (Integrity verified / Not
  yet sealed / Integrity check failed / Integrity unavailable) and a "View proof" dialog for
  batched entries (`GET /audit-logs/{id}/proof`, fetched only when opened). Copy says local Merkle
  batch, not a blockchain. Privacy-card copy corrected (append-only is application-enforced; a
  presigned link survives revocation for ≤ 5 min).
- **CI:** web job gains "Generated api-client is current" and "Production build". A backend spec
  drift step was deliberately **not** added (no Python lockfile → spurious diffs).
- **Docs** reconciled: README, CLAUDE.md, ROADMAP, TODO, this entry; `docs/*`, `scripts/README.md`,
  `CHANGELOG.md`, `DECISIONS.md` by a delegated pass (see CHANGELOG `[Unreleased]`).

### Quality gates (2026-10-25, local, working tree — not CI)

| Gate | Result |
|---|---|
| `pytest` (backend, `PULSEOS_TEST_POSTGRES_URL` unset) | **1351 passed, 26 skipped** (skips = opt-in PostgreSQL tests, not run) |
| `ruff format --check` / `ruff check` / `mypy` (strict, CI config) | clean (173 source files) |
| Web `format:check` / `lint` / `typecheck` | clean |
| Web tests (Vitest) | **689 passed** (hospital 252, patient 229, doctor 158, ui 33, api-client 17) |
| Web `pnpm build` | succeeds (Vite chunk-size advisory only) |
| New regression tests vs. original code | the 4 tamper/500 HTTP tests in `tests/test_audit_inclusion_regression.py` **fail on `0ea4bac`** and pass now |

Final-review fixes (same session): per-event anchors can no longer make a v3 event VERIFIED and
batch evidence takes precedence (3 forged-anchor tests fail on the pre-fix tree with `VERIFIED`,
pass now); each batch is rebuilt once per page (`verify_many`, 100 entries of a 256-leaf batch:
median 203.6 ms → 5.4 ms, local benchmark). New opt-in PostgreSQL test
`test_page_verification_on_postgres_uses_whole_batches_and_detects_tampering` was **not executed
on PostgreSQL** (Docker daemon not running, no native PostgreSQL) — run the `backend-postgres`
job or a disposable container before relying on `members_sharing_batch_with`.

Not run: PostgreSQL tests, any live stack (Firebase, MinIO, Redis, Ollama), browser checks.
Local Python is 3.14; CI uses 3.12.

### PO decisions (2026-10-25)

- **Approved:** ADR-027 decision-7 amendment — historical v3 per-event anchors stay stored and
  readable but cannot by themselves establish VERIFIED.
- **Approved:** `audit_batch_verify` 30/60 s and the any-role policy of `/audit-batches/{n}`.
- **Confirmed policy:** the uploading hospital keeps access to its own uploads even when the
  patient hides them (ADR-013 layer 2); this stays disclosed in the patient UI and documented.
- **Keep explicit:** the unsealed-v3 relabel-to-v2 limitation; no claim of protection against an
  attacker who can rewrite the database consistently.
- **Still open:** hospital rejection/suspension lifecycle and a verification audit event (the
  latter needs an ADR: `audit_logs.patient_id` is NOT NULL).

### Exact next step

Review the working-tree diff; commit it (suggested split: backend audit fixes + tests; AI audit;
web client regen + UI; CI; docs); push with the 4 earlier commits; confirm all CI jobs green,
including `backend-postgres` and the two new web steps. Then, before the review: seal batches on
the local stack with `scripts/audit_integrity.py seal --confirm-env local` so the integrity badges
show *verified* (sealing is manual), and rehearse the demo in TODO.md §6.

---

## Session 020 — 2026-10-17 · superseded by Session 021

**Branch:** `main` at `d09d721`, synchronized with `origin/main` (`ahead 0, behind 0`).
**CI Status:** GitHub Actions workflow for commit `d09d721` is **GREEN** (workflow run #17, user-provided evidence; run logs not in-repo).

### What landed since Session 019 (commits `a09d41f` through `d09d721`)

| Commit | What |
|---|---|
| `a09d41f` | **Authorization & audit correctness:** AI search audited (`AuditAction.RECORDS_SEARCHED`) and rate-limited (`ai_search`); patient lookup requires VERIFIED hospital (409); concurrent consent requests guarded with advisory locks and UNIQUE constraints; expired requests cleanly handled; 255-character upload filename validation |
| `7c27aa0` | **CI:** Run consent concurrency regression tests in `backend-postgres` job |
| `fd42b80` | **Docs:** Historical documentation reconciliation |
| `b08ba2a` | **Consent UI:** Patient portal partial per-category consent decisions and reload recovery |
| `98f3b33` | **Admin API:** Expose `GET /api/v1/hospitals` (requires `SYSTEM_ADMIN`); regenerated OpenAPI (39 operations under `/api/v1`) and `@pulseos/api-client` |
| `e350b2a` | **Audit integrity CLI:** Developer workflow (`scripts/audit_integrity.py`) for batch sealing and verification |
| `b045f10` | **Auth provisioning:** Local System Admin provisioning script (`scripts/dev_provision_system_admin.py`) and credentials path resolver |
| `e48017a` | **Auth recovery:** Hospital portal forced token refresh on profile 403 to preserve verified registration state |
| `96a2191` | **Admin UI:** Dedicated System Admin dashboard, layout (`AdminLayout`), metrics, and role-aware navigation |
| `d09d721` | **Record pagination:** Keyset pagination stabilized with deterministic composite ordering `(date_of_service, created_at, id)` and robust cursor encoding/decoding |

### Quality gates (measured 2026-10-17 at `d09d721`, local)

| Gate | Result |
|---|---|
| `pytest` (backend, no PostgreSQL URL) | **1209 passed, 25 skipped** (opt-in PostgreSQL tests; verified clean) |
| `mypy` | **clean** (166 source files) |
| `ruff format --check` / `ruff check` | **clean** (0 findings) |
| Web `typecheck` / `lint` / `format:check` | **clean** across all 6 packages |
| Web tests (Vitest) | **611 passed** (hospital 199, patient 188, doctor 166, ui 34, api-client 24) |
| GitHub Actions CI (`d09d721`) | **GREEN** (workflow run #17 succeeded; user-provided evidence) |

*Note: PostgreSQL integration tests were not run locally in Session 020; they run in CI under the `backend-postgres` job (run #17 result user-provided).*

### Verified implementation status & remaining gaps

1. **System Admin & Hospital Verification:**
   - Provisioning script (`scripts/dev_provision_system_admin.py`) sets custom user claims `{"role": "SYSTEM_ADMIN", "system_admin": True}` via Firebase Admin SDK.
   - Endpoint `GET /api/v1/hospitals` lists all hospitals for `Role.SYSTEM_ADMIN`.
   - Verification endpoint `POST /api/v1/hospitals/{hid}/verify` flips `is_verified=True`.
   - *Remaining gap:* Verification does not yet persist verifier user ID or timestamp on the row, nor emit an administrative audit log event. Hospital rejection/suspension is not implemented.
2. **Audit Integrity:**
   - Developer CLI (`scripts/audit_integrity.py`) supports `seal`, `verify-batch`, `verify-event`, and `reconcile` (backed by `AuditBatchService`).
   - *Remaining gaps:* CLI lacks production-safety guard; scheduled background sealing daemon, API v3 Merkle verification endpoint (`GET /audit-logs/{id}/verification` currently evaluates only legacy per-event `audit_anchors`), and patient UI integration remain outstanding. External anchoring (Polygon Amoy / M6.4) is deferred/not authorized.
3. **FHIR:**
   - Synthea R4 Phase A import works.
   - *Remaining gap:* FHIR export is still outstanding.
4. **Patient Identity:**
   - Patient QR identity remains open.

### Exact next step

Complete DOC-01 documentation reconciliation and validation report. Next roadmap candidates: FHIR R4 export, hospital verification metadata & administrative audit logging, scheduled audit sealing, or patient QR identity.

---

## Session 019 — 2026-10-15 · superseded by Session 020

*Historical — read Session 020 for the current state.*

**Branch:** `main` at `72b55e2`, level with `origin/main`. **Nothing from Sessions 018–019 is
committed** — the working tree holds, all uncommitted and awaiting PO review: Task 0 documentation;
the ruff cleanup of four test files; Task 1 (authorization and audit correctness: backend, tests,
regenerated API client); Task 1.1 (PostgreSQL tests and documentation reconciliation).

### Done
- **Task 1 — TODO §0a item 1, implemented.** AI search audited (`RECORDS_LISTED` /
  `ACCESS_DENIED`; refined to `RECORDS_SEARCHED` in Task 1.2) and rate-limited (`ai_search`); patient lookup requires a VERIFIED hospital
  (409); duplicate open requests, already-granted categories and second active grants → 409 under
  a per-(patient, clinician) advisory lock, with only UNIQUE violations mapped to 409; the
  PENDING → EXPIRED transition now persists (refusal returned, not raised) and listings show
  past-deadline requests as EXPIRED; upload file names over 255 characters → 422.
- **Task 1.1 — PostgreSQL validation.** Ran against a disposable PostgreSQL 16.15 container
  (`pgvector/pgvector:pg16` already present locally, `--rm`, tmpfs data, 127.0.0.1:55432; the dev
  database on 5433 was not touched; container stopped afterwards). New
  `tests/test_consent_postgres.py`: concurrent duplicate requests and concurrent approvals
  (each with a no-lock control that does duplicate), SQLSTATE-based integrity mapping, and the
  255-character multibyte filename at the column. Found and fixed two pre-existing failures in
  `test_alembic_postgres.py` (pinned to `0007`; 0008 had moved `head`).
- **Docs:** ADR-017, ADR-020 and ADR-021 amendments (explicit, dated, original text kept);
  SECURITY, AI_ARCHITECTURE, API_GUIDELINES, DEVELOPMENT_GUIDE, README, ROADMAP, TODO reconciled.
- **Task 1.2.** `AuditAction.RECORDS_SEARCHED` for the clinician AI search (ADR-020 amendment 2;
  no migration — verified on the migrated PostgreSQL schema); patient and hospital audit views
  label it; OpenAPI/client regenerated. `tests/test_consent_postgres.py` added to the CI
  `backend-postgres` job. ADR amendment statuses finalized (implemented, uncommitted, PO
  acceptance not recorded). GitHub Actions could not be checked (no `gh` / authenticated
  integration available); nothing has run on GitHub for these changes.

### Gates (2026-10-15, local — not GitHub Actions)
Backend 1165 passed / 25 skipped without the PostgreSQL URL; 1190 passed with it; the CI
`backend-postgres` command 25 passed, 0 skipped. Ruff format, ruff lint, mypy clean. Web 550
passed; typecheck, ESLint, Prettier clean.

### Decisions needed
Review and commit the working tree; formally accept the three ADR amendments.

### Exact next step
PO review/commit. Then TODO §0a item 2 (per-category consent UI).

---

## Session 018 — 2026-10-14 · superseded by Session 019

*Historical — read Session 019 for the current state.*

**Branch:** `main` at **`72b55e2`**, **level with `origin/main` — everything is pushed.** The
working tree was clean at the start of this session; the only changes made in it are the
documentation updates listed below (uncommitted, awaiting PO review).

**Phase:** M4 substantially done; M5 AI partially built; M6.1–M6.3 complete (local integrity
only); M6.4 not authorized; M7 not started. Preparing for the final academic review.

### What landed since Session 017 (from git history, verified against the code)

| Commit | What |
|---|---|
| `5381642` | Clinician AI retrieval excludes patient-hidden records |
| `10bec8f`, `4d8e181`, `2cb0851` | The ruff/format/mypy findings recorded in Session 017 fixed; SQLAlchemy 2.1 typing |
| `281439c` | Experimental E2E work removed (only lockfile and a README line were tracked); no E2E infrastructure exists or is planned for the final review |
| `15b2d1b` | **In-app notifications** (ADR-031): migration 0008, `notifications` module, four endpoints, consent integration in the same transaction, `@pulseos/ui` bell + drawer (30 s polling) in patient and doctor portals |
| `5690a93` | Automatic consent/permission refresh (`useApiResource` polling + focus refresh, 15–30 s) on patient consent inbox, grants, dashboard and doctor sent-requests, granted-records |
| `13e2034` | Doctor portal: granted categories marked and not re-requestable; AI assistant above granted records |
| `72b55e2` | PostgreSQL host port standardized to **5433** (container port stays 5432): compose, `.env.example`, `config.py` default, DEVELOPMENT_GUIDE |

### Work this session

1. Read-only initialization and a full read-only audit (identity, FHIR, consent, AI, audit
   integrity, portals, security, deployment). Key findings, all verified in code:
   - AI clinician search endpoint: raw chunk text, no audit event, no rate limit.
   - `GET /patients/lookup` works for PENDING-hospital admins (name disclosure).
   - v3 audit events always verify as `NOT_ANCHORED`; sealing/reconciliation run only in tests.
   - No SYSTEM_ADMIN provisioning, no admin UI; patient UI cannot decide per category; no backend
     duplicate-request guard; expired requests linger as PENDING; FHIR is import-only; QR missing.
2. **Documentation update (Task 0, docs only):** DECISIONS (ADR-031 status + implementation notes;
   ADR-008 note), CLAUDE, SESSION, ROADMAP (new §Final review priorities), TODO (new §0a), CONTEXT,
   README, and docs/{SYSTEM_ARCHITECTURE, DEVELOPMENT_GUIDE, BLOCKCHAIN_ARCHITECTURE,
   AI_ARCHITECTURE, API_GUIDELINES, DATABASE_DESIGN, TECH_STACK, SECURITY}. No application code,
   migration, dependency, container or database was touched.

### Decisions recorded

None new. ADR-031 marked **Implemented** (shipped; formal acceptance of its text not recorded).
ADR-030 remains **Proposed**. ADR-009, ADR-010 and ADR-026 remain placeholders.

### Quality gates (measured 2026-10-14 at `72b55e2`, local)

| Gate | Result |
|---|---|
| `pytest` (backend, no PostgreSQL URL) | **1127 passed, 18 skipped** (opt-in PostgreSQL tests; not re-run this session) |
| `mypy` | clean (162 source files) |
| `ruff format --check` / `ruff check` | **3 files / 12 findings — all in test files from `15b2d1b`**; CI `backend` job will fail until fixed |
| Web `format:check` / `lint` / `typecheck` | clean |
| Web tests | **549 passed** (patient 184, hospital 161, doctor 156, ui 31, api-client 17) |
| GitHub Actions | not checked this session |

### Exact next step

PO reviews and commits the documentation changes. Then, with authorization, implement the final
review priorities in order (ROADMAP §Final review priorities, TODO §0a): (1) authorization and
audit correctness, (2) per-category consent UI, (3) SYSTEM_ADMIN provisioning + hospital
verification, (4) demonstrable local audit integrity, (5) FHIR R4 export. Fixing the ruff
findings (TODO §0) is a cheap prerequisite.

---

## Session 017 — 2026-10-11 · superseded by Session 018

*Historical — its branch, push and lint statements are out of date (see Session 018).*

**Branch:** `main` at **`155cbf1`**, **38 commits ahead of `origin/main`, none pushed** (pushing is
a Product Owner action). **The working tree is not clean** — uncommitted, awaiting PO review:

- *Prerequisite (CI + tests):* `.github/workflows/ci.yml` (new `backend-postgres` job) and
  `backend/tests/test_alembic_postgres.py` (6 opt-in PostgreSQL migration tests).
- *Documentation alignment (this session):* README, `docs/` (AI, security, tech stack, system
  architecture, domain model, database design, blockchain, development guide, API guidelines,
  contributing, project overview), `scripts/README.md`, `contracts/README.md`, and `.claude/`
  (CLAUDE, CONTEXT, ROADMAP, TODO, CHECKLIST, DECISIONS, this file), CHANGELOG, and two
  `project-management/` files.
- *Local only, never to be committed:* `infra/docker-compose.yml` (PostgreSQL published on
  `${POSTGRES_PORT:-5433}:5432` to avoid a local port clash, plus editor whitespace changes).

**Phase:** M4 substantially done (unchanged since Session 016); **M5 AI partially built**;
**M6.1–M6.3 complete and accepted with deferred items**; **M6.4 not authorized**; M7 not started.

### What happened since Session 016 (from git history and code — no session entries were written)

No SESSION.md entries exist for 2026-10-04…10-11; this summary is reconstructed from commits and
verified against the code, not from session notes.

- **Audit anchoring foundation** — `b17c2f0` (2026-10-04): `AuditAnchor` port,
  `LocalChainAuditAnchor`, migration 0006, patient-facing per-event verification. The ADR it cites
  as ADR-026 was never written (placeholder in DECISIONS.md).
- **AI layer** — `a7df8b4`…`c95494a` (2026-10-04 to 2026-10-10): FHIR ingestion (migration
  `aedb0169a4eb`), consent-scoped lexical retrieval, context assembly, `AnswerGenerator`
  protocol, clinical assistant (doctor), Health Copilot (patient), rate limits; Gemini was added
  and then removed — **local Ollama (Qwen3:8B) is the only provider** (`c95494a`).
- **M6.1–M6.3** — `e3c0fe1` (implementation: v3 Keccak-256 digests, Merkle batches, commitments,
  sealing, database-only reconciliation, conflict classification), `1ce4c14` (opt-in PostgreSQL
  tests), `155cbf1` (ADR-019 resolution, ADR-027, ADR-004/023 amendments, status) — all
  2026-10-11.

### Decisions recorded

ADR-027 accepted (Merkle-batched anchoring); ADR-019 resolved; ADR-028 and ADR-029 accepted from
the PO's direction of 2026-10-11 (Ollama sole provider and redaction revisited; lexical retrieval,
pgvector deferred); **ADR-030 proposed** (Synthea/FHIR import, documents existing behaviour —
needs PO acceptance). ADR-009, ADR-010 and ADR-026 remain placeholders.

### Quality gates (measured 2026-10-11)

| Gate | Result |
|---|---|
| `pytest` (backend, local, no PostgreSQL URL) | **1088 passed, 18 skipped** (the 18 opt-in PostgreSQL tests) |
| Opt-in PostgreSQL tests (disposable PostgreSQL 16.15 container) | **18 passed** |
| `ruff check` / `ruff format --check` / `mypy` (repo-wide) | **39 / 20 files / 158 lines** — findings that appeared after Session 016's clean state, mostly in AI tests; none introduced by M6 |
| Web (`pnpm` checks and tests) | **not re-run** since Session 016 (463 tests then) |
| GitHub Actions | **not run** on any commit since `ea2ebd5` (unpushed) |

### Known gaps found this session

- **AI retrieval ignores hidden records:** a record a patient has hidden can still feed a
  clinician's AI answer if its category is granted. Documented in SECURITY.md; fixing it is an
  application-code change that has not been authorized.
- Stale source docstrings and a reference to the non-existent `scripts/anchor_audit_events.py`
  in `consent/router.py` (and therefore the generated OpenAPI/client) — application or generated
  artefacts, deliberately not edited by the documentation task.

### Exact next step

PO reviews the uncommitted prerequisite and documentation changes and decides whether to commit
them (excluding `infra/docker-compose.yml`). Then: decide on ADR-030, decide whether to authorize
the AI hidden-record fix, and define/authorize M6.4 (see the roadmap review proposals) — or return
to the open M4 items (notifications, QR, SYSTEM_ADMIN provisioning).

---

## Session 016 — 2026-09-08

**Read this entry alone to know where the project stands.** Everything below it is history.

**Branch:** `main`, working tree **clean**. Last feature commit **`ea2ebd5`** (patient record
visibility controls), which this entry describes; the docs commit that adds this entry follows it.
**20 commits ahead of `origin/main` at `ea2ebd5`, 21 including this documentation commit — none
pushed.** Pushing is a Product Owner action, deliberately not taken by a Claude session.

**Phase:** M4 — Core Features Complete, **substantially done**. All three web portals are built
and integrated against the real API; the M3 consent journey exists end to end in code and is
exercised over HTTP by `tests/test_m3_gate.py`. What remains in M4 is listed under *Not started*
below — chiefly `notifications` and QR identity.

### Quality gates (measured 2026-09-08 at `ea2ebd5`)

| Gate | Result |
|---|---|
| `pytest` | **653 passed**, **97% line coverage** (`--cov=app`) |
| `ruff format --check` / `ruff check` / `mypy` (strict) | clean — 116 files / 112 source files |
| `pnpm format:check` / `lint` / `typecheck` | clean, 6 workspace projects |
| `pnpm test` | **463 passed** — patient 169, hospital 161, doctor 129, api-client 3, ui 1 |
| `pnpm build` | **3/3 apps build** |

### Live local baseline (Docker Postgres, 2026-09-08)

| | |
|---|---|
| patients | **14** (10 Synthea + 3 demo seeds + 1 linked real account) |
| users | **22** |
| hospitals | **3** (all seeded VERIFIED) · doctors **4** |
| medical records | **890** (Synthea Phase A 889 + 1 earlier upload), all `PATIENT_LOCKER` origin |
| hidden records | **0** |
| consent requests **9** · grants **9** | audit_logs ~**208** (grows with any dev-portal use) |
| alembic head | **0005** |

Joaquin141 (`PHI-IND-2026-J0TA0DK`, 103 records) is the Synthea patient linked to a real Firebase
account via `scripts/dev_link_identity.py` — the account to demo with. **Do not mutate live data
during development** unless explicitly asked.

### Architecture (shape unchanged since M0.2; reach much extended)

Modular-monolith FastAPI backend (ADR-001), six modules — `auth`, `patients`, `records`, `consent`
implemented; **`ai` and `notifications` are still 4-line `__init__.py` docstrings**. Layering is
strict: **router → service → repository**; services import no FastAPI and own no transaction; one
session/transaction per request; cross-module access only through a published `directory.py` seam
or a Protocol. **12 tables, 5 Alembic migrations, 30 operations under `/api/v1`** plus `/health`
and `/ready`. **25 ADRs** recorded (ADR-009 and ADR-010 are still placeholders).

Web: pnpm workspace — three apps (**patient, doctor, hospital — all three now real**) over three
packages (`api-client` generated from OpenAPI, `config`, `ui` the shared foundation). Per-feature
frontend architecture everywhere: `src/<feature>/{api.ts, view.ts, use*.ts}` + dumb components,
all mapping in `view.ts`.

### What shipped since Session 015 (the 20 unpushed commits)

**Doctor portal — complete consent workflow** (`36cf81a`, on top of the slice-1 discovery flow).
Login → register → dashboard → patient search by Health ID → request access (per category, with
purpose) → sent requests → granted records → record detail → download. This is what made the M3
gate reachable; before it, no UI could *create* an access request.

**Hospital portal — built from a two-file scaffold to a working portal** (`7f6088e`, `ac08f3b`,
`fe9ea86`, `ceda3ad`, `58715a7`, `c35e2a7`). Shell + login, hospital self-registration, doctor
management (activate/deactivate), uploaded-records listing and detail, patient lookup by Health
ID (ADR-021) and upload confirmation.

**Hospital audit attribution and history** (`dad1c2f`, `b4a574f`, `7305a0e`, migration **0005**).
Hospitals emit audit events for their own reads (ADR-022) and get a hospital-scoped audit page.
Events now carry `actor_hospital_id` — the hospital as it was *at the time* — plus a versioned
audit-hash scheme (ADR-023). ADR-025 then fixed the patient's trail, which had been reading the
actor's *present* employer and so re-attributed history when a clinician changed hospital.

**Authenticated API rate limiting** (`8889588`, ADR-024). Per-route dependency, fixed windows over
Redis, fail-open, on the four Health-ID/discovery surfaces: `patient_lookup` 20/min,
`record_existence` 30/min, `granted_records` 30/min, `access_request_create` 10/min. Closes M3-D
for *authenticated* abuse only — see *Deferred*.

**Synthea FHIR R4 Phase A ingestion** (`2d92b28`). 10 pinned patients, 889 records mapped from
DiagnosticReport/Condition/MedicationRequest/Immunization/AllergyIntolerance into the existing
category vocabulary; sanitized raw FHIR JSON to S3/MinIO behind the same audited consent path.
Consent enforcement over imported records is proven in `tests/test_synthea_consent.py`. Phase B
is deliberately out — see *Deferred*.

**Patient record browsing** (`32d5644`). Chronological ordering by `date_of_service` (a real fix:
`created_at` is the transaction clock, so a bulk import collapsed the sort onto the UUID
tie-breaker), `sort=newest|oldest`, server-side `search` with LIKE metacharacters escaped, category
filter, cursor pagination with `DateCursor`, page size 25, Load more. A cursor issued under one
sort is refused under the other (422) rather than silently serving the wrong end.

**Patient audit history** (`fc2a029`, `34e6426`). Grouped hospital → actor → events, newest first
at every level, expand/collapse with sticky reader choices, own-activity toggle, Load more.
Grouping is a rearrangement and never a filter — asserted by test. "Your own activity" and
"Unattributed activity" (events predating migration 0005) are named rather than merged into a
hospital.

**Patient profile editing** (`fb1c329`, `b5ccf07`). `PATCH /api/v1/patients/me` — the API's first
PATCH. Three editable fields (`fullName`, `dateOfBirth`, `gender`); `healthId`, `firebaseUid`,
role, status and `createdAt` unreachable rather than merely undocumented. An `Unset` sentinel
distinguishes an omitted key from an explicit `null`. No migration, no audit action.

**Patient record hide/unhide** (`ea2ebd5`, this session). `PATCH /api/v1/records/{id}/visibility`
— the write path for `is_hidden`, a column that had existed since migration 0003 and been enforced
on every non-owner read since M3 with no way for a patient to set it. Scope is **any record the
patient owns, whatever its origin** (DOMAIN_MODEL §1/§3 amended from "own locker only"). Hiding
removes a record from every grantee surface at once and **revokes nothing**: the grant keeps its
status, categories and expiry, and the row, S3 key and file are untouched. No migration, no new
audit action.

**Portal login redesign** (`5f8ed4a`) and deterministic audit/health-ID tests (`5a8277c`).

### Architectural decisions implemented since Session 015

- **ADR-020** — clinician-scoped record listing (`/granted-records`) as its own resource with a
  chooser-only projection; a filter over grant scope, never a verdict.
- **ADR-021** — hospital patient lookup as a `patients`-owned identity endpoint, role-gated only.
- **ADR-022** — audit emission policy: what a hospital records, and what the schema cannot.
- **ADR-023** — historical hospital attribution + a versioned audit-hash scheme.
- **ADR-024** — rate limiting as a per-route dependency (middleware runs before authentication,
  so per-user keying is impossible there).
- **ADR-025** — the patient's trail attributes events to the hospital recorded *on the event*,
  while `StaffDisplayResponse` keeps its current-affiliation meaning. Two questions, two sources.

Standing rules worth re-reading before touching this code: consent is the single choke point;
`RecordNotFoundError` covers "exists but you may not see it" (404, never 403); audit rows are
append-only and written in the same transaction as the action; **audit digests are SHA-256 and
must become keccak256 before anything is anchored (ADR-019)**.

### Status by category — implemented / deferred / not started

**Implemented and tested**
Auth (Firebase, custom claims), patients (register / read / edit / lookup), records (upload,
listing with sort+search+filter+paging, detail, presigned download, existence projection,
grant-scoped listing, hide/unhide), consent (request → per-category decision → grant → revoke,
`enforce` on every non-owner read, append-only audit log), hospital + doctor onboarding and
management, hospital and patient audit views, authenticated rate limiting, Synthea Phase A import.
All three web portals.

**Deferred — decided, reasoned, and recorded in TODO.md**
Unauthenticated/pre-auth throttling (blocked on ADR-009); the organisation/actor-scoped
operational log (needs its own ADR; three audit gaps point at it, including that a grantee
refused for a *hidden* record produces no audit row at all); object-storage server-side
encryption (an unimplemented clause of accepted ADR-005, on the PHI path); the unlocked lazy
boto3 client build; Synthea Phase B (raw FHIR in JSONB, a real clinical-content field, orphan
Observations, Organization/Practitioner rows, full-corpus import, FHIR export); the
`(patient_id, date_of_service DESC, id DESC)` composite index; a hidden-only record filter.

**Not started — do not describe these as working**
`notifications` module (access requests arrive silently) · QR identity generation and scanning ·
hospital **bulk upload** and hospital-side **request management on behalf of their doctors** (both
in M4's original scope) ·
**SYSTEM_ADMIN provisioning**, so `POST /hospitals/{hid}/verify` has no reachable caller and a
self-registered hospital is stranded `PENDING` (masked because the three seeded hospitals are
already VERIFIED) · **M5 AI layer** — OCR, chunking, pgvector embeddings, RAG copilot, summaries;
`workers/tasks.py::record_uploaded` still only logs and acknowledges · **M6 blockchain** — the
`AuditAnchor` interface itself does not exist yet; nothing is anchored · **M7** — E2E tests
(no Playwright), performance pass, security review, deployment (ADR-009 unresolved, no
api/worker Dockerfile) · Flutter app (`mobile/` is a README, ADR-010 unresolved).

Also not real, and easy to mistake for real: the patient **Settings page is presentation only**
(everything from `src/data/settings.ts`; nothing persists, Export Data / Delete Account are
visual), the profile **Emergency contact card states its own absence** (not modelled), and the
top-bar global search is decorative.

### Testing debt

**No component or DOM tests exist** in any portal — all 463 web tests are pure logic (`view.ts`
mappers, `api.ts` with a stubbed client). No test would catch a broken button or a bad conditional
render. **No end-to-end coverage** either: one Playwright run over login → upload → request →
approve → read would guard the whole thesis of the product.

### Important development notes (still true)

- **`backend/.env` is read relative to the process CWD** (`make dev-api` runs from `backend/`);
  the root `.env` is docker-compose only. There is still **no `backend/.env.example`** — this gap
  has cost debugging time twice and is the oldest open item in TODO §0.
- Infrastructure must be running (`make up`) or every DB-touching request 500s — and a 500 carries
  **no CORS headers**, so a browser misreports it as a CORS failure. Curl `/ready` first.
- **Swagger at `/docs` cannot authenticate anything** — no OpenAPI `securitySchemes` is declared.
  Use curl with a real bearer token copied from the browser.
- Seeded staff and patients carry `synthetic:` subjects and **can never authenticate**; a real
  Google account always starts empty until `dev_link_identity.py` links it.
- **The database says who you are; the Firebase token says what you may do.** Any fixture that
  edits `users` must be followed by the matching `*/register` call — the only writer of claims.
- Category codes are the API vocabulary; internal category UUIDs never leave the backend.
- A dev stack may be running (`uvicorn --reload` + vite) and will write real `audit_logs` rows as
  the portal is used. Tests never touch the live DB — they use in-memory SQLite with faked
  auth/storage/queue.

### Next step

Nothing is half-finished; pick the next slice deliberately. In dependency order the strongest
candidates are: **(1)** the `notifications` module — the last M4 backend item, and the reason
access requests currently arrive silently; **(2)** SYSTEM_ADMIN provisioning, which unblocks the
hospital verification flow that today only works because the seed data pre-verifies; **(3)** a
first Playwright E2E over the consent journey, which is the cheapest insurance for a demo.
Follow the slice discipline: inspect → design report → approval → implement → gates → report →
commit.

---

## Session 015 — 2026-09-04

> **Superseded by Session 016.** Its quality-gate numbers, its "79 uncommitted files" warning
> and its milestone summary are all historical — the work it describes was committed, and much
> more has shipped since. Read it for the M4.1/M4.2 reasoning, not for project status.

**Branch:** `main`. Last commit `cca4925` (Firebase auth + local dev environment).
**⚠️ 79 files are uncommitted** — the whole of M4.1 and M4.2 plus the `@pulseos/ui` extraction
(see "Not committed" at the end of this entry). Commit before any other work.

**Phase:** M4 — Core Features Complete. M0/M2/M3 backends are done; the **patient portal is
fully integrated against the real API**; the **doctor portal's first vertical slice** is built.

### Quality gates (measured 2026-09-04)

| Gate | Result |
|---|---|
| `pytest` | **320 passed**, **97% line coverage** (`--cov=app`) |
| `ruff format --check` / `ruff check` / `mypy` (strict) | clean, 105 files / 100 source files |
| `pnpm typecheck` / `lint` / `format:check` | clean, 6 workspace projects |
| `pnpm test` | **131 tests** — patient 111, doctor 16, api-client 3, ui 1 |
| `pnpm build` | all three apps build |

### Architecture (unchanged in shape, extended in reach)

Modular-monolith FastAPI backend (ADR-001) with six modules — `auth`, `patients`, `records`,
`consent` implemented; `ai` and `notifications` are still `__init__.py` docstrings only.
Layering is strict everywhere: **router → service → repository**, services import no FastAPI and
own no transaction, one session/transaction per request, cross-module access only through a
published `directory.py` seam or a Protocol. 12 tables, 4 Alembic migrations, **25 operations
under `/api/v1`** plus `/health` and `/ready`.

Web: pnpm workspace, three apps (`patient` complete, `doctor` first slice, `hospital` still a
two-file scaffold) over three packages (`api-client` generated, `config`, **`ui` — now a real
shared foundation**).

### Backend state

Everything from M0.3/M2/M3 plus, this session:

- **`GET /api/v1/consent-grants`** (M4) — the patient's grant history with a derived
  `status` (ACTIVE / REVOKED / EXPIRED) computed from the same predicate enforcement uses.
- **`GET /api/v1/audit-logs`** (M4) — the patient-facing trail, keyset-paginated on
  `occurred_at`. Path is `/audit-logs`, **not** `/audit`: plural kebab-case per
  API_GUIDELINES:9, matching the `audit_logs` table.
- **Identity projection** (M4) — `records.directory.StaffDirectoryService` publishes
  display-safe staff facts (`full_name`, `specialty`, `hospital_name` — no ids, no employment
  status). Consent declares a `StaffDirectory` protocol; the boundary adapts it. Batched by
  construction: a collection in, a mapping out, **one statement per identity kind per page**
  (an N+1 guard test counts SQL statements). Feeds `requester` on the inbox, `grantee` on the
  grants listing, and `actor` on audit entries.
- **`GET /api/v1/records/existence?patientHealthId=`** (M4.1) — the clinician discovery step
  (SYSTEM_ARCHITECTURE §Consent Flow step 1). DOCTOR-only, must be ACTIVE (ADR-015). Returns
  `{items:[{code, displayName}]}` and nothing else: no ids, filenames, hospitals, dates,
  descriptions or **counts**. Hidden records excluded. One grouped SQL query.
- **Bug fix in `auth/firebase.py`** — an unresolved Firebase project id used to surface as
  `InvalidTokenError` → **401**, blaming the caller for the server's missing configuration
  (the SDK reports it with a bare `ValueError`, the same type it uses for a malformed token).
  `_get_app` now checks `app.project_id` and raises `AuthProviderUnavailableError` → **503**,
  which is what `core/config.py` always promised.

### Frontend state

- **Patient portal — complete and fully integrated.** All seven pages (Dashboard, Records,
  Consent, Grants, Audit, Profile, Settings) render real API data. **`src/data/` now contains
  only `settings.ts`** — every other mock module was deleted. Per-feature architecture,
  repeated six times: `src/<feature>/{api.ts, view.ts, use*.ts}` + dumb components; all mapping
  in `view.ts`; 111 tests, all pure logic.
- **Doctor portal — first vertical slice (M4.2).** Login → dashboard (name, hospital, ACTIVE
  badge, search card) → `/patients` search by Health ID → available categories. Wired to
  `GET /doctors/me` and `GET /records/existence`. **Access requests are not implemented yet.**
- **`@pulseos/ui` is now the shared foundation** (ADR-003: "share components, tokens", and do
  not triple auth plumbing). It holds the auth layer (`provider`, `firebase`,
  `firebaseAuthProvider`, `devMockAuthProvider`, `AuthContext`), `ProtectedRoute`,
  `LoadingScreen`, `apiResult`, `useApiResource`, `cn`, `initialsFor`, and **`tokens.css`**.
  Both apps import the same palette, so the surfaces cannot drift.
  **shadcn primitives are deliberately duplicated per app** — that is the shadcn model
  (`components.json` is per app), and sharing them would drag the whole UI kit into the
  package. When the hospital portal lands, a third copy is the signal to hoist.

### Authentication flow (verified end to end this session)

1. Google sign-in via the shared Firebase provider. Only three env vars are read:
   `VITE_FIREBASE_{API_KEY,AUTH_DOMAIN,PROJECT_ID}`.
2. `GET /patients/me` → **403** for a fresh account (`_to_authenticated_user` requires the
   `pulseos_role` / `pulseos_user_id` custom claims).
3. `POST /patients/register` (accepts a claim-less verified token) → creates `users` +
   `patients`, issues the Health ID, calls `set_custom_user_claims` **in the same transaction**.
4. Frontend force-refreshes the ID token; `GET /patients/me` → **200**.

**The rule to remember: the database says who you are; the Firebase token says what you may
do.** Any local fixture that edits `users` must be followed by the matching `*/register` call,
because that call is the only writer of custom claims.

### Recent implementation decisions

- **Grouping key for grants includes `status`** (not just grantee + grantedAt + expiresAt), so a
  half-withdrawn approval renders as two truthful cards rather than one that lies.
- **`/records/existence` deliberately does not call `consent.enforce`** — `enforce` answers "may
  this clinician read *this record*", unanswerable before any grant exists; gating discovery on
  it would make the consent flow unstartable. The relationship `records` *can* decide (ADR-015
  ACTIVE) is enforced instead. Everything past discovery still crosses the choke point once.
- **Discovery is not audited** — no record was accessed and no truthful `AuditAction` exists.
  Adding one is ADR-sized (ADR-018 is the precedent). **Open question, see TODO.**
- **The audit page's summary is page-scoped** and says so on every card; there is no aggregate
  endpoint and presenting a page total as a lifetime total would misrepresent a compliance record.
- **Health ID validation in the doctor portal is format-only.** The ISO 7064 check character
  stays in `patients/health_id.py`; a TypeScript copy would be free to drift.

### Important development notes

- **`backend/.env` is read relative to the process CWD**, and `make dev-api` runs
  `cd backend && uvicorn`. The root `.env` is **docker-compose only**. There is still no
  `backend/.env.example` — this gap has cost debugging time twice.
- Infrastructure must be running (`make up`) or every DB-touching request 500s — and a 500
  carries **no CORS headers** (Starlette's `ServerErrorMiddleware` sits outside
  `CORSMiddleware`), so browsers misreport it as a CORS failure. Curl `/ready` first.
- **Swagger at `/docs` cannot authenticate anything.** No OpenAPI `securitySchemes` is declared,
  because auth reads the raw `Authorization` header in a plain dependency rather than through a
  FastAPI security class. Use curl with a real bearer token copied from the browser.
- Seeded staff and patients carry `synthetic:` subjects and **can never authenticate**
  (`auth/seed.py` refuses non-synthetic subjects), so a real Google account always starts empty.
- Category codes are the API vocabulary; internal category UUIDs never leave the backend.
- Audit digests are SHA-256 and **must** become keccak256 before anything is anchored (ADR-019).

### Milestones

- **Current: M4 — Core Features Complete.** Done: patient portal integration, the three
  patient-facing listing APIs, the identity projection, the existence endpoint, doctor portal
  slice 1. Remaining: doctor access-request flow, hospital portal, notifications module.
- **Next: M5 — AI Layer** (OCR → chunk → embed → RAG copilot + summaries), which replaces the
  no-op body of `workers/tasks.py::record_uploaded`.

### Not committed

79 files: the M4.1 existence endpoint (`records` module + 4 test files), the entire doctor
portal (`web/apps/doctor/**`), the `@pulseos/ui` extraction (11 files moved with `git mv`,
36 patient files repointed), the regenerated api-client, and this documentation refresh.
**Next step: review and commit as two or three coherent commits** (backend M4.1 / shared-ui
extraction / doctor portal M4.2), then open the PR.

---

## Session 014 — 2026-09-01

**Phase:** M3 Consent Domain — backend implemented end to end. Branch `feature/consent`
(cut from `main` after the M2 merge). One commit so far (`a893611`, schema only); everything
after it is uncommitted — see "Not committed" below.

**Decisions (new ADRs):** ADR-016 records ⇄ consent bidirectional dependency; ADR-017
return-not-raise for audited read failures; ADR-018 `ACCESS_DENIED` audit action; ADR-019
SHA-256 digests until keccak256 (M6). All four came out of the final PR review, which found
them undocumented.

**Done — schema (migration 0004, five tables):** `ConsentRequest` (mutable: status),
`ConsentRequestCategory` (the normalised requested set), `ConsentDecision` (immutable),
`ConsentGrant` (mutable: `revoked_at` — what enforcement reads), `AuditLog` (append-only).
Two invariants pushed into the database and proven by rejected inserts: a decision can only
answer a **requested** category (composite FK into `consent_request_categories`), and an
approval spawns **exactly one** grant (unique `decision_id`). Append-only tables carry
`created_at` only — no `updated_at`, no `onupdate` — so the DDL cannot advertise a mutation
DATABASE_DESIGN principle 3 forbids. `AuditLog` has two timestamps on purpose: app-assigned
`occurred_at` (hashed, and the keyset order) and server-assigned `created_at` (not hashed),
which is what makes `event_hash` computable before the INSERT. Verified: zero drift vs
`Base.metadata` under `compare_type=True`; reversible `head→base→head` and `0004→0003→0004`.

**Done — repository:** five repositories, pure persistence, savepoints only where a
constraint is a domain signal, and error translation **per constraint** rather than per table
(a foreign-key violation and a unique violation on `consent_decisions` mean opposite things).
Unbounded listings keyset-paginated; bounded child collections returned whole.

**Done — service:** the full lifecycle — create request, patient inbox, clinician sent list,
approve, reject, revoke, and `enforce`. Every state change writes its audit event in the same
transaction, in the same private helper that performs the change. Clock and `event_hasher`
injected. `request_context` capped at 200 chars and stripped of control characters (the
service half of the unbounded-column fix).

**Done — HTTP:** six endpoints under `/access-requests` and `/consent-grants` (the paths
API_GUIDELINES names verbatim), one `to_http_error`, full failure sets declared in the spec
with `application/problem+json`, four-part docstrings on all six. The API speaks category
**codes**; a `CategoryVocabularySource` protocol translates.

**Done — integration:** routers mounted; `records/directory.py` publishes the clinician and
category seams; `records.service` gained a `ConsentEnforcer` port; `get_for_caller` is the one
authorization seam and takes an `action`, so downloads and metadata reads are distinguishable
in the trail. A second role gate (`RequireRecordReader`) admits clinicians to single-record
reads only — they still have no listing or upload scope. Hospital-admin own-upload reads are
unchanged (ADR-013 layer 2, decided in `records`). api-client regenerated: 17 → 23 paths.

**Tests: 194 → 268.** New: `test_consent_repositories.py` (10), `test_consent_service.py` (26),
`test_consent_http.py` (33), `test_m3_gate.py` (7 — the ROADMAP gate walked over HTTP across
two hospitals). Consent module coverage 99–100% per file; overall 97%. `tests/support.py` now
enables `PRAGMA foreign_keys=ON`, so constraints the migration declares are actually enforced
in tests — they were silently inert before, and all 194 pre-existing tests still passed once
it was on.

**Final review — merge blockers found and fixed:**
- **M3-A:** denied *downloads* were refused but not logged. `create_download_url` still raised,
  and the raise rolled back the `ACCESS_DENIED` row (`GET` had already been fixed; the edit had
  silently failed to match on `POST` and no test covered it). Fixed per ADR-017. Verified:
  404 + the audit row commits.
- **M3-C:** `is_hidden` was ignored, so a clinician holding a grant could read a record the
  patient had hidden. Now settled in `_authorize_read` **before** the choke point — hiding
  withdraws a record from the set consent can share, so there is no grant question to answer
  and no audit row is written. Owner and uploading-hospital behaviour unchanged.
- Four regression tests added; both defect tests confirmed red before the fix, green after.

**Review findings deliberately NOT fixed (see TODO):** listings write no audit (M3-B);
`POST /access-requests` is an unthrottled Health-ID existence oracle (M3-D); hospital-admin
denials are unaudited (M3-E); `AuditAnchor` interface not built (M3-G); plus ten minors.

**Gotcha worth remembering:** `DateTime(timezone=True)` round-trips **aware** on Postgres and
**naive** on SQLite. It bit twice — a `TypeError` comparing a persisted deadline with the
clock (fixed with `as_utc` in the consent service), and `revokedAt` serialising with and
without a `Z` in the same flow depending on whether the value was just assigned or re-read.
The second is still open. Any comparison between a persisted timestamp and `now()` needs
normalising.

**Not committed:** everything after `a893611` — the consent repository/service/HTTP layers,
`records/directory.py`, the records integration, all four test files, the doc updates in this
session, and the regenerated api-client. The seven consent scaffold files from the first M3
task are still untracked too.

**Not done:** notifications fan-out, `AuditAnchor`, the category-existence projection a
clinician needs to *discover* records, a patient audit-log endpoint, and all M3 frontend work
(doctor search + request flow, patient consent inbox and audit view). OD-1…3 were never signed
off — the implementation runs on the documented recommendations, with the 90-day grant expiry
as an injected default rather than a hard-coded rule.

**Next:** commit the branch, then close the remaining M3 review findings (M3-B/D/E/G) or
schedule them explicitly; then M3 frontend, which is what the gate demo actually needs.

---

## Session 013 — 2026-08-29

**Phase:** M2 Backend Core — full milestone implementation. Branch `feature/medical-records`
(cut from the merged `main`; PO approved starting M2 on 2026-08-28 and deferred the remaining
M0.3 gate items — Docker, live Firebase browser run — as later ops/validation tasks).
**Nothing committed** — suggested commit message in the session report.

**Decisions (new ADRs, flagged for PO review):**
- **ADR-014:** arq as the job queue (the choice ADR-008 deferred to M2 start). Enqueue-only
  `JobQueue` port in `core/queue.py` (Arq impl, lazy pool + in-memory fake); enqueue failure
  never fails an upload (job is advisory until M5's pipeline — logged, record stays UPLOADED).
- **ADR-015:** onboarding = self-registration + human verification. Hospital admin registers
  a NEW hospital (PENDING, random draw-and-insert `HID-XXXX`) and becomes its admin;
  SYSTEM_ADMIN verifies (`POST /hospitals/{hid}/verify`); doctors self-register to a VERIFIED
  hospital (PENDING) and the hospital admin activates/deactivates. Trust gap closed by the two
  verification steps instead of an invite pipeline (needs notifications — not built).

**Done (backend — records module + supporting seams):**
- **Models + migration 0003:** `Doctor` (1:1 User, one hospital, status PENDING/ACTIVE/
  DISABLED, registration_number), `HospitalAdmin` (1:1 User), `MedicalRecord` (FHIR
  DocumentReference-shaped: category FK, origin HOSPITAL_UPLOAD/PATIENT_LOCKER, provenance
  FKs, date_of_service, s3_key unique UUID-only, processing_status — M2 writes UPLOADED only,
  is_hidden column for the M4 locker UI). Reversible, named constraints, indexed FKs.
- **Storage port (ADR-005):** `records/storage.py` `ObjectStorage` ABC + `S3ObjectStorage`
  (the ONLY boto3 importer, lazy client via to_thread, SigV4, all SDK errors →
  `StorageUnavailableError`, sanitized Content-Disposition) + `records/fake.py`.
- **Services:** `organizations.py` `HospitalService` (register/verify/own-hospital, doctor
  register/list/activate — idempotent registrations mirroring the patients pattern, claims
  provisioned in-transaction) and `service.py` `RecordService` (uploads validate type
  {pdf,jpeg,png}/size/emptiness; flush row THEN put object — storage failure rolls back the
  row; enqueue `record_uploaded` after storage, tolerated failure). **M2 read paths are
  ADR-013 layer 2 only:** patient-own + hospital-own-upload; doctors have NO record access
  until M3 wires `consent.enforce()` + audit in front of `get_for_caller`/
  `create_download_link` (the single seam, documented in code).
- **API:** POST/GET `/records` (multipart upload; role-scoped listing, category filter,
  cursor pagination per API_GUIDELINES — new `shared/pagination.py` keyset helpers),
  GET `/records/{id}`, POST `/records/{id}/download-url` (presigned, TTL
  `PULSEOS_S3_PRESIGN_TTL_SECONDS`=300), GET `/record-categories`, `/hospitals/*` and
  `/doctors/*` per ADR-015. 404-not-403 everywhere existence could leak; 413/415/422/409/503
  mapped in `records/dependencies.py` (translator pattern from auth).
- **Worker skeleton (ADR-008/014):** `workers/main.py` WorkerSettings + `workers/tasks.py`
  no-op `record_uploaded` (logs opaque id only). Run: `arq app.workers.main.WorkerSettings`.
- **Cross-module seams (isolation-preserving):** `patients/directory.py`
  `PatientDirectoryService` (get_by_user_id / get_by_health_id — how records resolves
  patients), `VerifiedToken.string_claim()` (moved from patients service, reused by org
  registrations), `auth/seed.py` synthetic-user helper (refuses non-`synthetic:` subjects).
- **Seed:** demo admin + ACTIVE demo doctor per simulated hospital (`records/seed.py`),
  3 synthetic patients with pinned VALID Health IDs `PHI-IND-2026-1QE8DVR/5WD2FD4/AES1W87`
  (`patients/seed.py`); `scripts/seed.py` orchestrates all of it, still strictly idempotent.
- **Config:** `PULSEOS_S3_REGION`, `PULSEOS_S3_PRESIGN_TTL_SECONDS`,
  `PULSEOS_RECORDS_MAX_UPLOAD_BYTES` (15 MiB default); deps arq/boto3/python-multipart.

**Tests: 194 passing (106 → 194).** New: pagination cursors, queue port (arq mocked),
storage port (boto3 mocked, header-injection-safe disposition), records repositories
(keyset walk, scoping ValueError), org + record services (idempotency, HID redraw/
exhaustion, cross-hospital 404s, storage-failure atomicity via HTTP retry, queue-outage
tolerance incl. no-PHI log check), HTTP suites covering every M2 gate criterion (upload →
fake MinIO → queryable; patient blocked from hospital endpoints; doctor/system-admin have
zero record access), seed idempotency incl. demo actors + stable UUIDs, OpenAPI contract
pins for all new paths. Coverage on records module 88–100% (gate ≥80%). ruff + mypy strict
green; web gates green after `make api-client` regen (spec diff = the new M2 surface).

**Gotcha worth remembering:** SQLite stores `CURRENT_TIMESTAMP` without microseconds but
SQLAlchemy binds datetimes WITH them, so keyset `created_at = :cursor` could never match on
SQLite and cursor pagination looped forever (caught by a hanging test). Fix in `core/db.py`:
`TimestampMixin` uses `DateTime(timezone=True).with_variant(sqlite.DATETIME(
truncate_microseconds=True), "sqlite")` — storage and bind formats now identical on SQLite;
ties fall to the id tiebreaker; Postgres untouched.

**Live smoke:** unmigrated DB → clean exit 1 + hint; migrate → seed run 1 creates 3+10+3+3+3;
runs 2–3 create nothing; 0003 downgrade/upgrade round-trips. App boots with NO services and
answers 401 problem+json with `WWW-Authenticate: Bearer` on all new surfaces.

**Not done / still open:** M2 live verification vs real Postgres/MinIO/Redis (deferred PO ops
items, same list as the M0.3 gate); ops script to attach a real Firebase login to a seeded
hospital (needed for a live portal demo — TODO); rate limiting (TODO, needs live Redis);
content sniffing on uploads (parking lot); ADR-009/010, OD-1…3 sign-off, deck conflict,
Gemini key unchanged. ADR-015 awaits PO review (implemented per documented rationale).

**Next:** commit + PR `feature/medical-records`; PO runs the deferred ops checklist (one
`docker compose up` → migrate → seed → upload via API → file visible in MinIO console) to
close the M0.3 + M2 gates; then M3 — Consent Domain (needs OD-1…3 sign-off), with M1 design
items in parallel.

---

## Session 012 — 2026-08-28

**Phase:** 0 — M0.3 Walking Skeleton, final coding task: idempotent seed system.
Branch `feature/m0.3-patient-web` (still uncommitted incl. session 011; PO to commit —
suggested message in the session report).

**Done:**
- **records module gets its first models** (`records/models.py`): minimal `Hospital`
  (FHIR Organization — UUID PK, unique `hid` HID-XXXX business key, name, address,
  verification_status PENDING/VERIFIED) and `RecordCategory` (unique `code` +
  display_name; a seedable table, not a code enum, per DOMAIN_MODEL §1). Ownership
  note: Hospital sits in `records` because DATABASE_DESIGN's entity map hangs
  DocumentReference off Organization and ROADMAP M2 bundles hospitals with records;
  revisit at M2 if doctor management argues otherwise (a move would be a reviewed
  follow-up, not a schema change).
- **Migration 0002** (`create_hospitals_and_record_categories`): reversible, named
  constraints, same conventions as 0001; env.py imports records models.
- **Repositories** (`records/repository.py`): HospitalRepository / RecordCategoryRepository
  (get-by-business-key + add; persistence only).
- **Seed logic in the owning module** (`records/seed.py`): `seed_reference_data(session)`
  — insert-if-absent keyed on hid/code, never mutates existing rows, returns a
  SeedResult; constants: HID-0001 TMH Jamshedpur / HID-0002 CMC Vellore / HID-0003
  Apollo Hospitals (seeded VERIFIED — demo-ready), the exact 10 DOMAIN_MODEL categories.
- **`scripts/seed.py`**: orchestration only — app Settings → engine → one session/
  transaction → seed → summary; graceful exit 1 with a migrate hint on an unmigrated DB.
- **Tests: 106 passing (102 → 106).** Idempotency across 11 runs in separate sessions
  with stable counts AND stable UUIDs; exact documented reference data; backfill-only
  behavior (pre-modified row is neither duplicated nor overwritten); constants pinned to
  spec; migration-chain reversibility test extended to all four tables.
- **Live smoke (the actual script, file SQLite via PULSEOS_DATABASE_URL):** unmigrated
  DB → clean failure + hint; run 1 → 3+10 created; runs 2–10 → nothing; final counts 3/10.

**M0.3 code is now complete.** Gate demo remains blocked on PO items: Docker
(`make up`, migration + seed against real Postgres), GitHub push + CI, Firebase web
config for the browser flow. ADR-009/010, OD-1…3, deck conflict, Gemini key unchanged.

**Next:** commit + merge `feature/m0.3-patient-web`, then the M0.3 gate walk-through
with the PO; then M1 decisions.

---

## Session 011 — 2026-08-28

**Phase:** 0 — M0.3 Walking Skeleton, Part 3B: first end-to-end user flow (patient web).
Branch `feature/m0.3-patient-web`. **Nothing committed** — PO asked for a suggested
commit message only (see report).

**Done — API client generation (ADR-003):**
- `scripts/export_openapi.py` (deterministic spec → `web/packages/api-client/openapi.json`)
  + `scripts/generate-api-client.sh` + `make api-client`. Generator: openapi-typescript →
  `src/generated/schema.ts` (machine-owned; excluded from eslint/prettier), runtime:
  openapi-fetch. Hand-written part is only `src/index.ts`: `createPulseOSClient({baseUrl,
  getAccessToken, fetch?})` with a bearer-auth middleware (centralized — apps never touch
  fetch/headers), exported types (PatientProfile etc.), RFC 7807 `problemDetail` helper.
- Spec honesty fix: POST /patients/register now declares the idempotent 200 alongside 201.
- Backend contract tests (`test_openapi.py`) pin the paths + camelCase schemas the client
  is generated from.

**Done — patient portal (React 19 + react-router 7 + Firebase web SDK 12, modular):**
- `firebase.ts` (env-driven config, helpful error if unset; `.env.example` added),
  `AuthContext` (single onAuthStateChanged listener; Google-popup sign-in per ADR-011's
  documented fallback; signOut), `api.ts` (the app's single client instance),
  `ProtectedRoute` + `LoadingScreen`, `LoginPage`, `ProfilePage` (Health ID, name, DOB,
  gender, created date + sign-out; plain UI), routes `/login` and protected `/`.
- **Transparent registration** (`profile/loadProfile.ts`, pure + unit-tested): GET /me →
  403 ⇒ POST /register (fullName from displayName → email local part → placeholder) →
  `getIdToken(true)` refresh → retry /me once (no loop). 409 role-conflict and other
  problems surface their RFC 7807 detail.

**Done — small fixes:** CORS middleware (new `PULSEOS_CORS_ORIGINS`, default = the three
portal dev origins; Authorization allowed, X-Request-Id exposed; bearer-only so no
credentials) — required for any browser→API call, was missing entirely. Tests in
`test_cors.py`.

**Tests: backend 102 (95 → 102: openapi contract 4, CORS 3); web 10 (1 → 10: api-client
middleware/problemDetail 3, patient flow 6, ui 1).** All gates green: ruff, mypy strict,
pytest; prettier, eslint, tsc, vitest, `pnpm build` (3 portals).

**Not done / still open:** seed script stub (last M0.3 code item); real-Firebase live run
of the web flow needs a Firebase web app config in `.env.local` (PO); Docker + push/CI
still pending (PO) — the M0.3 gate demo needs both; ADR-009/010, OD-1…3 sign-off,
deck conflict, Gemini key unchanged.

**Next:** seed stub + M0.3 gate walk-through (register → Health ID → login → profile via
one `docker compose up`), then PO items; M1 design work can proceed in parallel.

---

## Session 010 — 2026-08-28

**Phase:** 0 — M0.3 Walking Skeleton, Part 3A: Patient Foundation (backend). First real
feature: persistence, registration, Health ID issuance, profile read. One commit.

**Part 1 — Health ID doc consistency (ADR-012 now the only format anywhere):**
- Fixed stale formats in PROJECT_OVERVIEW, DATABASE_DESIGN, API_GUIDELINES (which had
  cited the *rejected sequential* `PHI-IND-2026-000001` as its opaque-ID example),
  CONTEXT.md, CLAUDE.md, TODO.md.
- DOMAIN_MODEL's example `PHI-IND-2026-7K3M9QX` was **not a valid ID** (its true ISO 7064
  check char is `*`). Canonical example everywhere is now **`PHI-IND-2026-7K3M99X`** —
  genuinely valid, verified by a test.

**Done (backend):**
- **core/db.py:** metadata naming convention (deterministic constraint names);
  `UUIDPrimaryKeyMixin` + `TimestampMixin`; `get_db_session` now owns the transaction —
  one session + one transaction per request, commit on success, rollback on exception.
  Services never touch the session; repositories flush inside savepoints and translate
  IntegrityError into domain errors.
- **Models:** `auth/models.py` User (firebase_uid unique, role, status, phone/email from
  verified token claims); `patients/models.py` Patient (user_id FK unique 1:1, health_id
  unique business key, full_name, date_of_birth, gender). Enum columns are plain VARCHAR
  (non-native, no CHECK) — values enforced by the typed app layer. No cross-module ORM
  relationships; FK only.
- **Migration 0001** (`create_users_and_patients`): handwritten, reversible, named
  constraints; up/down/up round-trip tested. env.py imports module models.
- **Health ID (`patients/health_id.py`):** ADR-012 exactly — 6 crypto-random Crockford
  chars + ISO 7064 mod 37-2 check char over the alphanumeric ID body; case-insensitive
  offline validation. **One strengthening:** generation redraws when the check char falls
  outside Crockford (`I L O U *`, ~1/7 of draws) so issued IDs are unambiguous end to end;
  validation stays strict ISO 7064.
- **Auth extensions:** `set_custom_claims` on the provider port (Firebase impl via
  to_thread with error mapping; fake records claims + failure injection);
  `UserRepository`; `UserAccountService` (accounts.py — how other modules provision/look
  up identities; claim names stay auth-internal); `AuthService.verify_credentials`
  (authn without claims); `require_verified_identity` dependency + shared
  `to_http_error` translator.
- **Patients module:** repository / service / schemas / router per Clean Architecture.
  `POST /api/v1/patients/register` (auth: verified identity, claims NOT required):
  idempotent — existing account returns 200 with the same profile and re-provisions
  claims (self-healing); fresh account: create User → draw-and-insert Patient (redraw on
  health_id collision, 8-attempt cap) → provision claims **inside the request
  transaction** (provider failure ⇒ full rollback, verified by test) → 201.
  Role-mismatch → 409. `GET /api/v1/patients/me` behind RequirePatient (404 if row
  missing). Shared `RequestModel` base (extra="forbid" per API_GUIDELINES).
- **Tests: 95 passing (59 → 95).** Health ID (format, randomness, doc example validity,
  exhaustive single-substitution + adjacent-transposition detection, Crockford-safe check
  chars, invalid shapes incl. sequential style); repositories (CRUD, duplicate
  translation, session usable after contained failures); service (register/idempotent/
  role-conflict/collision-redraw/exhaustion/claims incl. failure); HTTP (201/200
  idempotency, 401, 422 incl. unknown fields + future DOB, **atomicity on claim failure:
  503 then retry gets 201 not 200**, /me after simulated token refresh, /me 403 wrong
  role, /me 404 missing row); migration up/down/up; Firebase set_custom_claims mapping.
  ruff + mypy strict green.

**Gotcha worth remembering:** pysqlite implicitly commits around SAVEPOINT — it silently
broke request-transaction rollback in the SQLite test harness (NOT in Postgres). Fixed
with SQLAlchemy's documented recipe (tests/support.py `create_sqlite_test_engine`:
driver isolation_level=None + explicit BEGIN event). Any future SQLite-backed test must
use that helper.

**Deliberately not done:** frontend/login page, api-client generation, QR, doctor/
hospital modules, records, `/ready` migration-status check, rate limiting.

**Still open:** unchanged PO items (push + CI, Docker, OD-1…3 sign-off, ADR-009/010,
deck conflict, Gemini key).

**Next:** M0.3 Part 3B — OpenAPI client generation script (scripts/), patient web login →
profile page (Firebase web SDK → register/me), seed stub; then verify the M0.3 gate
end-to-end (needs Docker + push for CI).

---

## Session 009 — 2026-08-26

**Phase:** 0 — M0.3 Walking Skeleton, Part 2: Authentication Foundation (ADR-011, ADR-013).
Auth infrastructure only — no DB models, no migration, no registration, no frontend.

**Done (backend `app/modules/auth/` + one shared schema base, one commit):**
- **Auth port (ADR-011):** `provider.py` — `AuthenticationProvider` ABC + provider-agnostic
  `VerifiedToken`; `firebase.py` — `FirebaseAuthProvider` (the ONLY file allowed to import
  firebase_admin; lazy init off the event loop via `asyncio.to_thread`, named app "pulseos",
  service-account file or ADC; every SDK error mapped to domain errors — expired/invalid/
  disabled → 401-class, cert-fetch/init/unknown → `AuthProviderUnavailableError` → 503; no
  SDK detail or token ever leaks or is logged); `fake.py` — `FakeAuthProvider` (register
  user/claims/error per token) for tests and credential-free dev.
- **Domain:** `domain.py` — `Role` StrEnum (PATIENT/DOCTOR/HOSPITAL_ADMIN/SYSTEM_ADMIN,
  SCREAMING_SNAKE per DOMAIN_MODEL) + frozen `AuthenticatedUser(user_id, firebase_uid, role)`
  — the only identity object other modules may depend on. `errors.py` — domain exceptions.
- **Custom claims:** `pulseos_role` + `pulseos_user_id` (namespaced — Firebase reserves bare
  `user_id` in ID tokens). Set by registration in Part 3; verified here. Authentic token
  without claims → 403 `UnprovisionedAccountError` (authn ok, authz fails).
- **Service:** `service.py` — framework-free `AuthService`: Bearer-header parsing (case-
  insensitive scheme, strict shape) → provider verify → claims→`AuthenticatedUser` mapping.
- **Dependencies:** `dependencies.py` — `get_auth_provider` (reads `app.state.auth_provider`,
  overridable in tests), `require_authenticated_user` (single place tokens are verified;
  domain→RFC 7807 translation incl. RFC 6750 `WWW-Authenticate` challenges), `CurrentUser`
  alias, `require_role(*roles)` factory (ADR-013 layer 1) + `RequirePatient`/`RequireDoctor`/
  `RequireHospitalAdmin`/`RequireSystemAdmin`.
- **Router:** `GET /api/v1/auth/me` (identity introspection; camelCase wire shape). New
  `app/shared/schemas.py` `ApiModel` base (camelCase alias per API_GUIDELINES) — first
  resident of `shared/`, used by all future modules.
- **Core fix:** `core/errors.py` now propagates `HTTPException.headers` into problem+json
  responses (WWW-Authenticate/Retry-After were silently dropped before).
- **Config:** `PULSEOS_FIREBASE_CREDENTIALS_FILE` (optional; unset → ADC; without either,
  auth endpoints answer 503 and the rest of the API works). `.env.example` updated.
  `firebase-admin>=6.5` added; mypy override for the untyped SDK (no py.typed).
- **Tests: 59 passing (17 → 59).** Unit (header parsing, claim mapping, unprovisioned
  variants), Firebase provider with SDK fully mocked (error-mapping matrix incl. broken
  credentials path — never contacts Google), HTTP (missing/malformed/invalid/expired token,
  authenticated /me, forged role claim, provider-down 503, role gates incl. multi-role,
  wrong-role 403, SYSTEM_ADMIN blocked from all clinical gates, 401-before-403 ordering).
  ruff format/lint, mypy strict green.
- **Live smoke (real provider, no credentials):** app boots, /health 200, /auth/me → 401
  problem+json with correct challenge; token absent from all JSON logs.

**Deliberately not done:** users table/migration (Part 3 with patients), registration/claim
provisioning, rate limiting on auth endpoints (no rate-limit infra exists yet — M2-ish),
api-client regen (generator still doesn't exist — Part 3).

**Still open:** unchanged PO items (push + CI verification, Docker install, OD-1…3 formal
sign-off, ADR-009/010, deck conflict, Gemini key).

**Next:** M0.3 Part 3 — `patients` module (registration + claim provisioning via the auth
port, Health ID issuance per ADR-012, profile read), first Alembic migration (users +
patients), OpenAPI client generation script, patient login → profile page, seed stub.

---

## Session 008 — 2026-08-26

*(Numbering per PO's count; no session 007 entry exists in this log.)*

**Phase:** 0 — M0.3 Walking Skeleton, Part 1: Database Foundation & Project Plumbing.
PO directive to begin M0.3 implementation is taken as approval of the M0.2 design.
No business features, auth, consent, AI, or blockchain — plumbing only.

**Done (backend `app/core/` + Alembic, one commit):**
- **Dependencies:** sqlalchemy[asyncio]≥2.0, asyncpg, alembic, redis; dev: aiosqlite (lets DB
  and Alembic tests run without Docker/Postgres).
- **`core/db.py`:** `Base` (DeclarativeBase, Alembic's metadata target), `create_db_engine`
  (lazy-connecting, pool_pre_ping), `create_session_factory`, `get_db_session` request-scoped
  dependency. Engine/factory live on `app.state` via lifespan — no module-level globals.
- **Alembic:** `backend/alembic.ini` + async `env.py` (URL from Settings, overridable via
  `sqlalchemy.url` for tests/ops), reversible-migration `script.py.mako`, empty `versions/`.
  **No migration generated** — the first one lands with the first real models. Verified via
  CLI (`heads`, `history`, offline `upgrade head --sql`) and tests (online upgrade vs SQLite).
- **`core/logging.py`:** JSON formatter (timestamp/level/logger/message/request_id/extras,
  redacted-by-design: no bodies, no query strings), `configure_logging` routes uvicorn through
  it; `request_id` contextvar stamps every log line in a request.
- **`core/middleware.py`:** `RequestContextMiddleware` — X-Request-Id generate/propagate/echo
  + one access-log line per request (method, path, status, duration_ms).
- **`core/errors.py`:** RFC 7807 `application/problem+json` handlers (HTTPException,
  validation with `errors[]`, unhandled-500 that never leaks internals), per API_GUIDELINES.
- **`core/health.py`:** router with `/health` (moved from main) and `/ready` (DB `SELECT 1` +
  Redis PING as overridable dependencies; 200 ready / 503 unready with per-check detail).
- **`main.py`:** lifespan wiring, middleware, handlers, router; `PULSEOS_LOG_LEVEL` setting
  added (+ .env.example).
- **Tests: 17 passing** (health, ready ok/db-down/redis-down, RFC 7807 shapes incl. 500
  leak-check, request-id behavior, JSON formatter fields, access-log fields, session factory +
  dependency via SQLite, Alembic online + offline smoke). ruff format/lint, mypy strict green.
- **Live smoke (no services):** `/ready` → 503 `{"database":"failed","redis":"failed"}` with
  correlated JSON logs — graceful degradation confirmed.

**Deliberately not done:** models/tables/migrations, auth, module routers, api-client regen
(OpenAPI surface changed only by /ready; generation script still doesn't exist — M0.3 Part 3).

**Still open:** Docker still not installed (compose/`make up` unverified; `/ready` against real
Postgres+Redis untested); push + GitHub CI run still pending; Spring-Boot-vs-FastAPI deck
conflict, OD-1…3 formal sign-off, ADR-009/010, Gemini key — all PO items.

**Next:** M0.3 Part 2 — `auth` module (Firebase port + verification dependency + role claims),
then Part 3 — `patients` (registration, Health ID issuance per ADR-012, profile) + first
Alembic migration + OpenAPI client generation + patient login/profile page.

---

## Session 006 — 2026-08-25

**Phase:** 0 — foundation verification & preparation (PO directive: implementation officially
starting; this session prepares the scaffold, no business logic).

**Done:**
- Full repo re-analysis + implementation handoff report produced (previous turn of this session).
- **Verification, all green:** backend — ruff format --check, ruff check, mypy strict, pytest 2/2
  (Python 3.14.6 venv; one harmless Starlette TestClient deprecation warning). Web — pnpm
  install --frozen-lockfile, prettier --check, eslint, tsc (3 apps), vitest 1/1, and `pnpm build`
  succeeds for all three portals. `infra/docker-compose.yml` parses as valid YAML with the four
  expected services — but **Docker is still not installed**, so `make up` remains unverified.
- **Consistency fixes (docs/comments only, no architecture changes):** the session-003 milestone
  renumbering (walking skeleton M0.2 → M0.3) had never been applied outside `.claude/` — fixed
  stale M0.2 references in README §Status, CHANGELOG 0.1.0 notes, `backend/app/main.py` docstring,
  `scripts/README.md`, and the three web placeholder comments (`ui/index.ts`, `ui/index.test.ts`,
  `api-client/index.ts`). CHANGELOG gained an [Unreleased] entry recording M0.2 (docs-only) and
  the renumbering. `scripts/README.md` now acknowledges `review1_deck/` as presentation tooling.
- **.gitignore:** added a local-assets block excluding the Synthea corpus (`FHIR_Dataset/fhir/`,
  1.3 GB), the 81 MB Synthea zip, `Research Papers/` (copyrighted third-party PDFs — remote
  `kr-Sanket/Pulse-OS` may be public), `*.pptx`, and `PulseOS_Project_Plan.pdf`. The small
  `FHIR_Dataset/*.py` exploration scripts stay tracked. Reversible by deleting the block.
- **First commits made** (PO's session directive "keep commits small and clean" taken as commit
  approval; **nothing pushed** — push not explicitly requested): gitignore/asset hygiene + docx
  removal from tracking; M0.1 scaffold; docs + session history; Synthea exploration scripts.

**Decisions:** research PDFs/datasets/decks stay out of version control (see .gitignore rationale).
No architectural changes; ADR-001 (FastAPI) untouched — the Spring-Boot/Synthea deck conflict from
session 005 remains **open for the PO**.

**Still blocked / next:** PO to (1) resolve Spring-Boot-vs-FastAPI deck conflict, (2) approve
M0.2 design + OD-1…3, (3) push to GitHub + verify CI, (4) install Docker and verify `make up`,
(5) decide ADR-009/010, confirm Gemini + key. Then begin M0.3 walking skeleton
(order: Alembic wiring → logging/RFC 7807 → auth module → patients module + Health ID →
OpenAPI client gen → patient login/profile page → seed stub).

---

## Session 005 — 2026-07-29

**Phase:** paused — Review-1 presentation rebuilt around the research-paper corpus + Synthea dataset.

**Done:**
- Read all 11 papers in `Research Papers/` (via subagents) and built a fresh, literature-grounded
  Review-1 deck → **`PulseOS_Review1.pptx`** (23 slides, project root). Covers all 7 mandatory
  template sections (Title/Aim/Abstract/Lit Review/Research Gap/Objectives+SDG/References-IEEE)
  plus dataset, pipeline, hybrid DB, RAG, consent, blockchain, stack, roadmap slides. Speaker
  notes with transitions on every slide.
- Literature: 3-slide review table (AI-over-FHIR / blockchain / consent clusters), capability-gap
  matrix, and a quantified gap claim from the 55-study consent SLR (revocation propagation:
  described in 5/55, measured in 0) — proposed as PulseOS's headline evaluation metric.
- Dataset slide uses **measured** numbers from `FHIR_Dataset/fhir/`: 1,180 bundles, 527,113
  resources (~447/patient, 1.3 GB), with per-resource-type counts.
- Deck generator kept at `scripts/review1_deck/` (build.py + helpers.py) for regeneration.
- **Refinement pass (same session):** deck trimmed 23 → **20 slides** and rewritten in simple,
  student-style English per PO feedback: lit review cut to the 6 primary papers over 2 slides
  (contribution / limitation / what PulseOS takes), KB merged into the AI slide, pipeline + DB
  design merged, benchmarks and research-paper jargon removed, speaker notes shortened to
  3–5 bullet points per slide. Same visual design; regenerate via `python3 build.py`.
- **Visual redesign pass (same session):** every slide rebuilt as visual-first layouts per PO
  direction (keep theme/footer/palette, drop text blocks): emoji icon cards for problem/
  objectives/outcomes/future scope, 5-tile abstract flow, single-slide literature matrix,
  ✓/~/✗ research-gap matrix, hub-and-spoke proposed solution, layered architecture diagram,
  native bar chart of FHIR resource distribution on the dataset slide, on-chain/off-chain
  blockchain infographic, 3×3 tech-stack tile grid, milestone timeline roadmap, two-column
  references. Word density now ~50–120 words/slide.

**⚠ Deviation to reconcile:** per the PO's brief, the deck presents **Spring Boot (Java)** as the
backend-API layer (with Python/LangChain AI services) and the Synthea corpus as data source —
this conflicts with ADR-001 (FastAPI modular monolith) and the 3-simulated-hospitals plan. If the
pivot is real, ADR-001 and PROJECT_OVERVIEW need amendment; if not, edit slide 20 (Tech Stack).

**Manual edits still needed in the PPTX:** faculty guide name (slide 1 placeholder).

**Next step:** unchanged — M0.3 blocked on PO approval of M0.2 design + OD-1…3.

---

## Session 004 — 2026-07-21

**Phase:** paused — no development work (PO directive). Review-1 presentation prepared.

**Done:**
- Built the Review-1 deck **inside the faculty template** (`Review 1.pptx`, VIT/SCOPE): filled
  the 7 mandatory template slides (Title, Aim, Abstract, Literature Review, Research Gap,
  Objectives + SDG/outcome markers, References) and added 15 story slides using the template's
  own layouts, master, and theme colors → **22 slides**, Problem → Solution → Architecture →
  Plan → Outcome. Original template backed up as `Review 1 (original template).pptx`.
- All references are real (MedRec, FHIRChain, OmniPHR, RAG/NeurIPS, Med-PaLM/Nature, ABDM, FHIR).
- Deliberately excluded engineering internals (Docker, CI, endpoints, schema) per review-1 scope.

**Manual edits still needed in the PPTX:** member names/reg numbers, guide name, course code
(kept as `<<placeholders>>` on slides 1 and 19).

**Next step:** M0.3 walking skeleton remains blocked on PO approval of M0.2 design + OD-1…3
(see session 003). Do not resume implementation until the PO says so.

---

## Session 003 — 2026-07-20

**Phase:** 0 — M0.2 Domain Foundation & Identity Design ✅ complete (design-only, no code)

**Done:**
- **docs/DOMAIN_MODEL.md** (new): 8 core entities (User, Patient, Doctor, Hospital,
  MedicalRecord, RecordCategory, AccessRequest, Consent split into immutable ConsentDecision +
  active ConsentGrant, AuditEvent), relationship diagram, cardinal rules, RBAC permission
  matrix, Health ID design, open decisions OD-1…3.
- **ADR-011:** auth evaluation (Firebase vs Keycloak vs Authentik vs custom JWT, scored) →
  Firebase Auth confirmed, confined behind an auth port.
- **ADR-012:** Health ID `PHI-IND-YYYY-XXXXXXC` — crypto-random Crockford Base32 + ISO 7064
  check char; supersedes master plan's sequential examples (enumeration risk); FHIR identifier
  list for future ABHA.
- **ADR-013:** RBAC = role gate → relationship check → consent check; SYSTEM_ADMIN role added
  with a hard no-PHI invariant.
- Consistency updates: SECURITY.md (4 roles, 3-layer authz, no-admin-break-glass invariant),
  API_GUIDELINES.md (sort convention, X-Request-Id, Retry-After), CLAUDE.md doc map + status,
  ROADMAP.md (M0 split: M0.1 ✅ / M0.2 ✅ / M0.3 walking skeleton next).

**Key design choices to surface at review:** consent grants are per individual doctor + per
category with default 90-day expiry (OD-2); random non-sequential Health IDs; hospitals retain
access only to records they uploaded; System Admin can never read medical content.

**Open decisions blocking M0.3:** OD-1 (unclaimed patients — recommend no for MVP),
OD-2 (grant expiry default — recommend 90d adjustable), OD-3 (grant exposes health profile —
recommend yes, shown explicitly on consent screen). Plus still-open ADR-009 (deploy target),
ADR-010 (Flutter timing).

**Next step:** PO/architect approval of DOMAIN_MODEL.md + OD-1…3 → begin M0.3 implementation.
Nothing committed this session (M0.1 scaffold also still awaiting first commit approval).

---

## Session 002 — 2026-07-20

**Phase:** 0 — M0.1 Engineering Workspace & Project Scaffold ✅ complete

**Done:**
- Full repository scaffold per approved architecture: `backend/` (FastAPI modular monolith
  skeleton: app factory, `/health`, env-driven settings, six empty module packages),
  `web/` (pnpm monorepo: 3 Vite/React app shells on ports 5173/5174/5175 + `@pulseos/config`,
  `@pulseos/ui`, `@pulseos/api-client`), `mobile/`, `contracts/`, `scripts/` (placeholder
  READMEs), `infra/docker-compose.yml` (pgvector Postgres, Redis, MinIO + bucket bootstrap,
  named volumes, healthchecks), `.github/workflows/ci.yml`.
- Tooling configured and **verified green locally**: ruff format+lint, mypy strict
  (pydantic plugin), pytest (2 passing) · prettier, eslint 9 flat config, tsc strict
  (5 projects), vitest (1 passing), patient portal `vite build` succeeds.
- Root: `.editorconfig`, `.env.example` (milestone-annotated), `Makefile` (make ci = local CI),
  README rewritten as self-sufficient quickstart, `CHANGELOG.md` started (0.1.0).
- Deviation from task wording, approved in-session: **ruff format instead of Black**
  (matches docs/CONTRIBUTING.md; one tool for lint+format).
- Build backend switched hatchling → setuptools (hatchling editable install broke on the
  local Python 3.14 toolchain).

**Environment notes (this machine):** Python 3.14 (project targets ≥3.12 — fine), Node 24,
pnpm 10.12.1 via corepack shims in `~/.local/bin` (add to PATH!), **Docker NOT installed** —
compose file is untested against a real daemon; verify at next session (see TODO).

**Deferred intentionally:** Alembic wiring (belongs to M0.2 with the first migration, since
M0.1 forbids schema work). No commits made yet — awaiting PO approval of the scaffold.

**Next step:** PO reviews scaffold → first commit → M0.2 (walking skeleton: Firebase auth,
Health ID issuance, patient profile end-to-end). ADR-009/010 still open.

---

## Session 001 — 2026-07-20

**Phase:** 0 — Foundation & Planning

**Done:**
- Read `PulseOS_Project_Plan.docx` (master plan) in full.
- Performed independent architecture review; proposed and documented major revisions:
  modular monolith instead of microservices (ADR-001), pgvector instead of FAISS (ADR-002),
  React monorepo for the three portals (ADR-003), hash-only on-chain consent anchoring behind a
  pluggable interface (ADR-004), S3/MinIO only — Cloudinary dropped (ADR-005), FHIR-aligned
  metadata (ADR-006), LLM provider abstraction with PHI redaction (ADR-007), Redis-backed async
  job queue (ADR-008).
- Created the full `.claude/` + `docs/` documentation foundation (17 files).
- Initialized git repository (`main` branch). Nothing committed yet — awaiting Product Owner review.

**Open questions for Product Owner (blocking M1, not M0):**
1. Flutter app timing — build in parallel from Month 4, or after web portals stabilize? (Recommendation: after; see ROADMAP.md.)
2. Primary LLM provider — Gemini (free tier, recommended for budget) vs OpenAI.
3. Deployment target — Render (simpler, recommended) vs raw AWS.

**Next step (start of next session):**
- If Product Owner approved the plan: begin **M0 — Walking Skeleton** per ROADMAP.md
  (repo scaffolding, docker-compose with Postgres/Redis/MinIO, FastAPI skeleton with auth +
  Health ID issuance, patient web shell, CI pipeline).
- If not yet approved: address review feedback, update ADRs.

**Danger notes:** None yet. No application code exists.
