# TODO.md — Actionable Task List

> Remaining work only. Completed work lives in SESSION.md and CHANGELOG.md.
> Dependency ordered: each section unblocks the ones below it.
> Owner codes: FE (frontend lead), BE (backend lead), AI (AI+blockchain lead), PO (product owner), ANY (whoever/Claude).

**Milestones:** M0 ✅ · M2 ✅ · M3 ✅ (gate criteria met in code) · **M4 substantially
done — `notifications`, QR and SYSTEM_ADMIN provisioning remain** · **M5 (AI) partially built**
· **M6.1–M6.3 ✅** (M6.4+ **not authorized**) · M7 (hardening/deploy/paper) **not started**.

State as of `155cbf1` plus uncommitted prerequisite and documentation changes, 2026-10-11.
Full picture: [SESSION.md](SESSION.md) §Session 017. Milestone status is owned by ROADMAP.md.

---

## 0. Immediate — small, unblocked, cheap

*(The 79-uncommitted-files item that stood here is done: everything is committed. The branch is
~20 commits ahead of `origin/main` and entirely unpushed — pushing is a PO action.)*

- [ ] ANY: add **`backend/.env.example`**. `backend/.env` is read relative to the process CWD
      (`make dev-api` runs from `backend/`), while the root `.env` is docker-compose only. The
      absence of an example is what makes that invisible; it has cost debugging time twice.

## 1. M4 — Core Features Complete (current milestone, substantially done)

Shipped and **not** listed below: all three portals, the doctor consent workflow, the hospital
portal and its audit history, authenticated rate limiting, Synthea Phase A, patient record
browsing/search/sort/paging, patient audit grouping, patient profile editing, and patient record
hide/unhide. See ROADMAP.md §M4 for the full ✅ list.

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
- [ ] BE: **no code path provisions `Role.SYSTEM_ADMIN`**, so `POST /hospitals/{hid}/verify`
      has no reachable caller and self-registered hospitals are stranded `PENDING`. Masked in
      demos because the three simulated hospitals are seeded `VERIFIED`.
- [ ] BE: **`notifications` module** — in-app notification on request created / decided /
      revoked. Architecture decided in **ADR-031** (in-app delivery, transactional persistence
      in consent transaction, polling; arq dropped for notifications). ADR-031 is finalized and
      awaiting Product Owner review. Implementation is pending approval (currently an empty
      `__init__.py`; access requests arrive silently).
- [ ] FE: QR identity generation + scanning (ROADMAP M4 scope).

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
- [ ] BE: **FHIR export** — ADR-006 promised the mapping is trivial in both directions and
      only the import half now exists. A reviewer will notice the asymmetry.
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
      the ADR).
- [ ] PO: Resolve the Review-1 deck conflict — Spring Boot + Synthea (slide 20) vs ADR-001
      FastAPI + the 3-simulated-hospital plan. Amend the ADRs or fix the slide.

## 4. Testing debt

- [ ] FE: **no component or DOM tests exist.** All 463 web tests are pure logic (`view.ts`
      mappers and `api.ts` modules with a stubbed client); no test would catch a broken button,
      a bad conditional render or a layout regression. Add jsdom + Testing Library for the
      interactive paths.
- [ ] ANY: **no end-to-end coverage.** The first-login flow was proven with a throwaway script,
      not a committed test. One Playwright run — login → register → upload → request → approve
      → read — would guard the whole thesis of the product.
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
- [ ] BE: **Clinician AI search returns raw chunk text with no audit event and no rate limit**
      (`GET /api/v1/ai/patients/{id}/search`; SECURITY.md). Needs a decision before code changes.
- [ ] BE: The hidden-record regression tests use the SQLite harness only, so the
      `backend-postgres` CI job does not run them; the PostgreSQL run was a one-off local
      validation.
- [ ] PO: M5 gate restatement or missing features — OCR, summary, timeline, explainer and the
      redaction requirement are not built (ROADMAP §M5); no RC-3 evaluation exists.
- [ ] PO: Define and authorize M6.4 (or not) — receipts/submission, scheduler, CLI, contract and
      toolchain, Amoy access are all open (ROADMAP §M6, roadmap review proposals).
- [ ] BE: Stale source docstrings (`app/workers/__init__.py`, `workers/tasks.py`,
      `records/models.py` processing status) and the `scripts/anchor_audit_events.py` reference in
      `consent/router.py` → regenerate the OpenAPI/client after fixing. Code + generated
      artefacts; not done by the documentation task.
- [ ] ANY: Repo-wide ruff (39), ruff format (20 files) and mypy (158 lines) findings that appeared
      after Session 016 — the `backend` CI job cannot go green until they are fixed.
- [ ] PO: Database-level append-only enforcement for audit/consent/batch tables (M7 hardening).
- [ ] ANY: First GitHub Actions run of the new `backend-postgres` job after pushing; verify it
      actually runs and does not skip.

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
