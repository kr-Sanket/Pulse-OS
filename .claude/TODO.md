# TODO.md — Actionable Task List

> Remaining work only. Completed work lives in SESSION.md and CHANGELOG.md.
> Dependency ordered: each section unblocks the ones below it.
> Owner codes: FE (frontend lead), BE (backend lead), AI (AI+blockchain lead), PO (product owner), ANY (whoever/Claude).

**Milestones:** M0 ✅ · M2 ✅ · M3 ✅ (gate criteria met in code) · **M4 substantially
done — notifications, per-category consent decisions, System Admin provisioning/directory/dashboard and verifier metadata shipped; QR, the verification audit event and hospital rejection remain** · **M5 (AI) partially built** · **M6.1–M6.3 ✅** (local only, CLI sealing workflow available; M6.4+ **not authorized**) · M7 (hardening/deploy/paper) **not started**.

State as of 2026-10-25: Session 021's series and the four earlier commits are pushed to
`origin/main`; its CI result is in GitHub Actions (last in-repo record: run #17 on `d09d721`). Full picture: [SESSION.md](SESSION.md) §Session 021. Milestone status is owned by ROADMAP.md.

---

## 0. Immediate — small, unblocked, cheap

- [x] ANY: **fix the ruff findings introduced by `15b2d1b`** (3 files to format, 12 lint
      findings, test files only) — fixed and committed in `a09d41f`.
- [x] ANY: two `tests/test_alembic_postgres.py` tests asserted `0007` after upgrading to `head`,
      which 0008 (`15b2d1b`) broke — pinned to `0007`, committed in `a09d41f`.
- [x] PO/ANY: check the GitHub Actions results for the pushed commits, including the first run
      of `backend-postgres` (it must run, not skip) — workflow for `d09d721` was reported green (run #17, user-provided evidence).
- [ ] ANY: add **`backend/.env.example`**. `backend/.env` is read relative to the process CWD
      (`make dev-api` runs from `backend/`), while the root `.env` is docker-compose only. The
      absence of an example is what makes that invisible; it has cost debugging time twice.

- [x] PO: Session 021 work reviewed, committed and pushed with the 4 earlier commits (2026-10-25).
- [ ] PO/ANY: confirm that push's CI run is green, including the first run of "Generated
      api-client is current" and "Production build" (CI runs Python 3.12; local used 3.14).
- [x] PO: hidden-record policy — **confirmed 2026-10-25**: the uploading hospital keeps access to
      its own uploads when the patient hides them; keep it disclosed and documented.
- [x] PO: `audit_batch_verify` (30/60 s) and the any-role `/audit-batches/{n}` policy — accepted
      2026-10-25, together with the ADR-027 decision-7 amendment.
- [ ] ANY: backend OpenAPI drift check in CI — blocked on a Python lockfile (CI could resolve
      different FastAPI/Pydantic versions and produce spurious spec diffs).

## 0a. Final review priorities (status 2026-10-25)

Recommended order 1 → 2 → 3 → 4 → 5. Summary in ROADMAP.md §Final review priorities.
Items 1, 2, 4 and 5 are implemented for the review item 3 is partial.

1. [x] BE: **Authorization and audit correctness** — implemented in `a09d41f`, `7c27aa0`
   (ADR-017/020/021 amendments). AI search audited (`AuditAction.RECORDS_SEARCHED`) + `ai_search`
   rate limit; patient lookup requires a VERIFIED hospital (409); duplicate open requests /
   already-granted categories / second active grant → 409 under a per-pair advisory lock, with only
   UNIQUE violations mapped to 409; the EXPIRED transition now persists and listings show past-deadline
   requests as EXPIRED; upload file names over 255 characters → 422. Validated on SQLite and
   PostgreSQL (`tests/test_consent_postgres.py`). Follow-ups:
   - [x] ANY: add `tests/test_consent_postgres.py` to the `backend-postgres` CI job's file list
         — committed in `7c27aa0`; verified in CI (run #17, user-provided evidence).
   - [x] BE/FE: a dedicated audit action for the AI search — `RECORDS_SEARCHED`, committed in
         `a09d41f` (ADR-020 amendment 2). No migration; OpenAPI/client regenerated; patient and
         hospital audit views labelled.
   - [ ] BE: the AI search query travels in the URL query string (GET); a POST body would keep it
         out of intermediary logs but is a v1 contract change.
   - [ ] BE: request expiry is lazy — no sweep; the stored row becomes EXPIRED only when someone
         tries to answer it (listings already show it as EXPIRED).
   - [ ] BE: the patient lookup is still unaudited (operational-log question, §1).
   - [x] ANY: watch the first GitHub Actions run of `backend-postgres` with
         `tests/test_consent_postgres.py` — verified passed in CI (run #17, user-provided evidence).
   - [ ] BE: an intermittent `aiosqlite` "Event loop is closed" thread warning (a warning, not a
         failure) appeared once in the full suite run with the PostgreSQL URL set, from the SQLite HTTP
         fixture in `tests/test_consent_http.py`; it did not recur in three reruns. Likely the fixture's
         engine outliving its event loop — not investigated.
   - [ ] FE: the doctor portal marks already-granted categories but not categories that already
         have an open (pending) request from the same doctor; asking again is refused with 409,
         and the API's message is shown.
   - [ ] BE/FE: a legacy pair of open requests for the same category (only possible from data
         written before the duplicate guard) makes approving the second one a 409 for the whole
         multi-category approval, because the patient portal approves every category at once;
         the patient must reject the duplicate.
   - [x] ANY: stale comment in `.github/workflows/ci.yml` above the `backend-postgres` job —
         resolved in DOC-01.
   - [x] ANY: ROADMAP §M4's gate status still cites the 2026-10-14 figures — resolved in DOC-01.
2. [x] FE: **Granular consent decisions** — implemented and committed in `b08ba2a`. Patient
   `PendingRequestCard` lets the patient choose categories to approve and decline; confirms
   before revoking; grants reconcile cleanly across page reloads.
3. [-] BE/FE: **SYSTEM_ADMIN provisioning and hospital verification** — partially implemented
   in `b045f10`, `98f3b33`, `e48017a`, `96a2191`. Local provisioning script sets Firebase custom claims;
   `GET /api/v1/hospitals` lists directory for `Role.SYSTEM_ADMIN`; dedicated System Admin dashboard and
   `AdminLayout` with metrics and verification controls in hospital portal.
   Verifier user ID and timestamp recorded since `15e0b1c` (migration 0009).
   *Remaining gaps:* administrative audit event not emitted (needs ADR: `audit_logs.patient_id` is
   NOT NULL); hospital rejection/suspension lifecycle is not implemented (PO policy decision).
4. [x] BE/FE: **Demonstrable audit integrity (local only)** — CLI (`e350b2a`), sealing guard
   (`278bbfc`), API v3 verification/proof/batch endpoints (`c7e5359`), and Session 021
   inclusion required for VERIFIED everywhere, proof endpoint 500 fixed, patient
   integrity badge + proof dialog.
   - [ ] BE: sealing scheduler (`audit_batch_interval_seconds` is configured but unused).
   - [ ] BE: append-only enforcement in the database (trigger/REVOKE) — needs a migration + ADR.
   Public-chain anchoring stays deferred (Polygon Amoy / M6.4 not authorized).
5. [x] BE/FE: **FHIR R4 export** — `GET /records/export/fhir` (`2e05ee4`, re-check `0ea4bac`);
   patient portal download (Session 021). Still open:
   - [ ] BE: validate exported Bundles with an HL7 validator (none in the toolchain today).
   - [ ] BE: DocumentReference entries for uploaded PDFs/images (currently excluded).
   - [ ] BE: `subject`-matches-bundle-Patient check in the importer.
   - [ ] FE: doctor-portal export (API exists; no UI).
   Out of scope: FHIR server, SMART on FHIR, FHIR write-back.

## 1. M4 — Core Features Complete (current milestone, substantially done)

Shipped and **not** listed below: all three portals, the doctor consent workflow, the hospital
portal and its audit history, authenticated rate limiting, Synthea Phase A, patient record
browsing/search/sort/paging, patient audit grouping, patient profile editing, patient record
hide/unhide, in-app notifications (ADR-031, `15b2d1b`), automatic consent/permission refresh
(`5690a93`) and granted-category indicators (`13e2034`). See ROADMAP.md §M4 for the full ✅ list.

What is left, ordered by dependency. Each item is demonstrable on its own.

- [ ] BE: **unauthenticated/pre-auth throttling.** ADR-024 closed M3-D for *authenticated*
      abuse on the four Health-ID/discovery surfaces. An unauthenticated flood is still
      unthrottled and costs one Firebase verification each. Needs IP keying, which needs
      trusted-proxy semantics — there is no `ProxyHeadersMiddleware` and `X-Forwarded-For` is
      client-controlled, so this is blocked on **ADR-009** (deployment target). The key
      format already reserves `ip:{addr}`.
- [ ] BE: **organisation/actor-scoped operational log.** Three deferred items now point at
      this one missing artifact, and it should be designed once rather than three times:
      the hospital record-*listing* event (spans many patients, so unrepresentable in a
      NOT NULL `patient_id` table), and audit for `GET /patients/lookup` and
      `GET /records/existence` (only *successful* probes are representable, so the
      patient-visible log would miss the enumeration it would exist to catch). ADR-023 §
      Deferred records the reasoning. Needs its own ADR before any schema.
- [x] BE: **SYSTEM_ADMIN provisioning and directory** — implemented in `b045f10`
      (`scripts/dev_provision_system_admin.py`) and `98f3b33` (`GET /api/v1/hospitals`). Dedicated
      System Admin dashboard and `AdminLayout` in hospital portal implemented in `96a2191`.
      Verifier/timestamp persisted since `15e0b1c`. Remaining gaps: administrative audit event
      not emitted; rejection/suspension lifecycle not implemented.
- [x] BE/FE: **`notifications` module** — shipped in `15b2d1b` per ADR-031 (in-app only,
      written in the consent transaction, polled by the patient and doctor portals). Follow-ups,
      not scheduled: notification items do not link to the referenced request; the hospital
      portal has no notifications (out of scope in ADR-031).
- [ ] FE: QR identity generation + scanning (ROADMAP M4 scope; format fixed by ADR-012,
      `pulseos://p/v1/<healthId>`). Not among the five final-review priorities.

### Deferred from patient hide/unhide (shipped 2026-09-08)

- [ ] BE: **a grantee refused because a record is hidden produces no audit row at all.**
      `RecordService._authorize_read` returns before reaching `consent.enforce`, so the one
      denied access the patient cannot see in their trail is an attempt on a record they hid.
      The current behaviour is deliberate (asking consent would either log a view that never
      happened or a denial of a grant that is in fact valid) but it leaves a real hole, and
      the fix belongs with the operational-log ADR above rather than in a records patch.
- [ ] BE: **hide/unhide itself is unaudited**, by the same reasoning that left a profile edit
      unaudited: `AuditAction` has no truthful member for an owner's own administrative action.
      If it is ever wanted, it is `RECORD_HIDDEN`/`RECORD_UNHIDDEN` — no migration (VARCHAR(32)
      values, the ACCESS_DENIED/RECORDS_LISTED precedent), but a third method on the
      deliberately-two-wide `RecordAuditor` protocol, its own ADR, and a typed frontend ripple
      through the exhaustive `ACTIONS` map in the patient audit view.
- [ ] FE: **no way to list only hidden records.** They appear in place with a badge, which is
      right at 0–few; a patient who hides dozens has no way to review them as a set. Wants a
      `hidden` filter on `GET /records` before it is worth building, and neither exists yet.

## 1b. Deferred from the Synthea import (Phase B)

Phase A shipped ten pinned patients and 889 records; these are the parts deliberately left out.

- [ ] BE/PO: **raw FHIR in a JSONB column + GIN index.** Phase A stores each resource as its
      S3 object, which needs no migration and keeps the bytes behind the audited consent
      path. A queryable column is a different decision and **needs its own ADR**: ADR-006
      explicitly declines to run a FHIR server, and the "hybrid storage" plan the Review-1
      slide describes is in no ADR or design doc. Only worth it once something queries FHIR
      fields in SQL.
- [ ] BE/FE: **a real clinical-content field.** Phase A puts the document title in
      `original_filename` and the clinical line in `description` (OD-S2, Path 1), because
      the patient portal renders `originalFilename` as the record heading. It is honest and
      cost nothing, but "filename" holding a title is a semantic abuse a proper column +
      response field + UI section would retire.
- [ ] BE: **orphan Observations** — vital signs and loose labs with no DiagnosticReport
      parent (100 of the canonical patient's 443). Skipped per OD-S4; would need a per-
      Encounter vitals record and a `VITALS` category.
- [ ] BE: `CarePlan` / `CareTeam` / `Goal` / `ImagingStudy` / `Device` — mapped to nothing.
- [ ] BE: **Organization / Practitioner as first-class rows.** Deliberately not done: a
      `Doctor` needs a `users` row (a fabricated identity) and a `Hospital` would pollute the
      three-simulated-hospital demo *and* grant ADR-013 layer-2 read access to imported
      records. Their names survive as text inside the stored FHIR.
- [ ] BE: **full-corpus import via arq** for the other 1,170 patients; the mapping layer is
      already pure so the worker can reuse it unchanged.
- [x] BE: **FHIR export** — built (`2e05ee4`); see §0a item 5 for what remains.
- [ ] BE/PO: **`SYNTHETIC_IMPORT` record origin.** Phase A reuses `PATIENT_LOCKER` (OD-S1,
      zero ripple). A truthful value costs the backend enum + OpenAPI + client regen + the
      exhaustive `ORIGIN_LABELS` map in `@pulseos/ui`.

- [ ] BE: **composite index `(patient_id, date_of_service DESC, id DESC)`** for the record
      listing. Not needed now and deliberately not added: `EXPLAIN ANALYZE` shows a bitmap
      index scan on the existing `patient_id` index feeding a top-N heapsort over one
      patient's ~100 rows at 0.36 ms (890-row table). The index would let Postgres skip the
      sort and stream from the index — worth it once a patient holds low thousands of
      records, which the deferred full-corpus import (260k Observations) would cause.

## 2. Deferred M3 review findings (backend)

Each is a stated security or correctness gap. M3-D is closed by ADR-024.

- [ ] BE: **systemic** — no security event survives a failed request; ADR-017 covers the two
      read paths only. The durable fix (independent audit sink or outbox) needs its own ADR and
      changes DOMAIN_MODEL §1's same-transaction rule.
- [ ] BE: `ObjectStorage.put_object` sends no `ServerSideEncryption`; ADR-005 says
      "server-side encryption on". Unimplemented clause of an accepted ADR, on the PHI path.
- [ ] BE: `S3ObjectStorage._get_client()` builds the boto3 client lazily inside worker threads
      with no lock, unlike `FirebaseAuthProvider`, which guards the identical pattern.
- [ ] BE: minors — `revokedAt` serialises naive on SQLite / aware on Postgres
      (API_GUIDELINES:28); records' read endpoints declare only 200/422 in the spec; the
      request-expiry sweep and the `(patient_id, status, …)` inbox index are absent;
      `get_request_context` is duplicated in two modules; three names for one concept
      (`ConsentRequest` / `/access-requests` / DOMAIN_MODEL's `AccessRequest`).

## 3. Product-owner decisions (blocking later milestones)

- [ ] PO: **Retrospectively sign off OD-1…3.** M3 shipped on the documented recommendations:
      OD-1 unclaimed patients NO; OD-2 grant expiry 90d as an injected service default
      (`DEFAULT_GRANT_TTL`), overridable per approval; OD-3 grant exposes health profile —
      **not implemented either way**, so a ruling still changes code. See DOMAIN_MODEL.md §5.
- [ ] PO: Review ADR-015 and **ADR-016…024** — all implemented per their documented rationale.
- [ ] PO: **ADR-009** deployment target (Render vs AWS) — still a placeholder, and M7 has no
      api/worker Dockerfile without it.
- [ ] PO: **ADR-010** Flutter timing — still a placeholder; `mobile/` is a README.
- [ ] PO: **Accept or amend proposed ADR-030** (Synthea FHIR import as built; open questions in
      the ADR). Still Proposed as of 2026-10-14.
- [ ] PO: **Formally accept ADR-031's text** (optional bookkeeping) — the implementation shipped
      in `15b2d1b`, and the ADR status now says "Implemented", but no explicit acceptance of the
      written decision is recorded; its implementation notes list one deviation (no
      `NotificationDispatcher` interface).
- [ ] PO: **Amend ADR-021** if §0a item 1 makes the patient lookup require a VERIFIED hospital.
- [ ] PO: Resolve the Review-1 deck conflict — Spring Boot + Synthea (slide 20) vs ADR-001
      FastAPI + the 3-simulated-hospital plan. Amend the ADRs or fix the slide.

## 4. Testing debt

- [ ] FE: **no DOM tests exist.** The 550 web tests (2026-10-15) are almost all pure logic
      (`view.ts` mappers, `api.ts` modules with a stubbed client, shared hooks); the few component
      tests use `renderToString`. No test would catch a broken button, a bad conditional render
      or a layout regression. Add jsdom + Testing Library for the interactive paths.
- **No end-to-end suite, by decision.** The E2E infrastructure was removed (`281439c`) and is not
  to be rebuilt for the final review. Cross-portal journeys rely on the backend HTTP tests
  (`tests/test_m3_gate.py` and others) and manual walk-throughs (§6).
- [ ] BE: move the consent OpenAPI contract pins from `test_consent_http.py` (which still
      builds a throwaway app) into `test_openapi.py`; the routers are mounted in `app.main` now.

## 5. M1 — Research & Design (parallel, still open)

- [ ] ALL: Literature review — 3 papers each on HIE consent, blockchain audit, RAG
      summarization; notes into `docs/`.
- [ ] FE: Figma — the 3 core journeys (CONTEXT.md). *Note: all three portals were built without
      it, so this is now documentation of what exists as much as design of what will.*
- [ ] AI: Spike — EasyOCR vs Tesseract accuracy on 5 synthetic Indian lab-report PDFs.

## 5b. M5 / M6 follow-ups (recorded 2026-10-11; each needs authorization before code changes)

- [x] BE: **AI retrieval ignores hidden records** — a hidden record of a granted category can
      still feed a clinician's AI answer (SECURITY.md, AI_ARCHITECTURE.md). Needs a code fix plus
      tests; not yet authorized. *Fixed 2026-10-11: clinician retrieval filters `is_hidden` in
      the query; the patient copilot is unchanged. Regression tests in
      `tests/modules/ai/test_hidden_record_retrieval.py`, validated on SQLite and on a disposable
      PostgreSQL 16.15.*
- [x] BE: **Clinician AI search returns raw chunk text with no audit event and no rate limit** —
      fixed 2026-10-15 (§0a item 1).
- [ ] BE: The hidden-record regression tests use the SQLite harness only, so the
      `backend-postgres` CI job does not run them; the PostgreSQL run was a one-off local
      validation.
- [ ] PO: M5 gate restatement or missing features — OCR, summary, timeline, explainer and the
      redaction requirement are not built (ROADMAP §M5); no RC-3 evaluation exists.
- [ ] PO: Define and authorize M6.4 (or not) — receipts/submission, scheduler, CLI, contract and
      toolchain, Amoy access are all open (ROADMAP §M6, roadmap review proposals).
- [-] BE: Stale source docstrings — `app/workers/__init__.py`, `workers/tasks.py` and the
      `records/models.py` processing status fixed on `feature/upload-ai-indexing` (client
      regenerated); the `scripts/anchor_audit_events.py` reference in `consent/router.py` remains.
- [ ] PO: review `feature/upload-ai-indexing` — text-layer PDF indexing (proposed ADR-033, new
      `pypdf` dependency), citation-marker reconciliation, FHIR export record count, audit
      accessibility, download revoke delay, test-harness engine disposal.
- [ ] BE: OCR for images and scanned PDFs — not built; needs its own ADR (local engine choice,
      accuracy, CPU cost). Until then only text-layer PDFs join AI retrieval.
- [x] ANY: Repo-wide ruff (39), ruff format (20 files) and mypy (158 lines) findings recorded
      2026-10-11 — fixed in `10bec8f`/`4d8e181`/`2cb0851`; mypy is clean at `72b55e2`. New ruff
      findings from `15b2d1b` are tracked in §0.
- [ ] PO: Database-level append-only enforcement for audit/consent/batch tables (M7 hardening).

## 6. Ops / demo readiness

- [ ] PO/ANY: run the full local stack once and keep it running: `make up`, `alembic upgrade
      head`, `scripts/seed.py`, all three portals, a real Firebase login. Verify an upload lands
      in MinIO. This is also the outstanding half of the M0.3 / M2 / M3 gates: each has every
      criterion met in code and covered by tests, and none has had its live browser walk-through.
      (M4's own gate additionally needs the items in §1 above.)
- [ ] BE: consider mapping database-connection failures to **503** (as Firebase and storage
      outages already are). Today a dead database is a 500 "An unexpected error occurred" with
      no CORS headers, which reads to a browser as a CORS bug. `/ready` already reports it
      correctly, so this is diagnosability, not correctness.
- [ ] BE: consider declaring `HTTPBearer(auto_error=False)` as a documentation-only dependency
      so OpenAPI emits `securitySchemes` and Swagger gets an Authorize button. Enforcement
      would not change; the spec currently under-documents that endpoints need credentials.

## 7. Built but deliberately not wired (presentation only)

Not TODO items and not defects — shipped UI with no backend behind it, listed so nobody mistakes
them for working features or re-reports them as bugs. Each needs a product decision before it
becomes work.

- **Patient Settings page** — every toggle comes from `web/apps/patient/src/data/settings.ts`.
  Nothing persists; Export Data and Delete Account are visual. The backend models no patient
  preferences, so there is no endpoint to mirror.
- **Emergency contact card** (patient profile) — states its own absence rather than showing a
  stand-in. PulseOS does not model an emergency contact (DOMAIN_MODEL §1).
- **Top-bar global search** in the patient portal — decorative; the Records page has the real,
  server-side search.
- **Share / Print** on the record details panel — no backend exists for either.

## Parking Lot (not now)

- Emergency QR security design (break-glass) — Phase 2, needs its own ADR.
- OpenAPI-driven contract tests between web client and backend (schemathesis).
- Synthetic medical-record generator for realistic seed/eval data (needed by M5 evals).
- Content sniffing (magic bytes) on uploads — currently trusts the declared content type after
  allowlisting; revisit in the M7 security pass.
- Per-hospital breakdown on `GET /records/existence` (SYSTEM_ARCHITECTURE:67 mentions it;
  shipped category-only because naming the organisations is a disclosure the patient has not
  consented to).
