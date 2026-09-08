# TODO.md — Actionable Task List

> Remaining work only. Completed work lives in SESSION.md and CHANGELOG.md.
> Dependency ordered: each section unblocks the ones below it.
> Owner codes: FE (frontend lead), BE (backend lead), AI (AI+blockchain lead), PO (product owner), ANY (whoever/Claude).

**Milestones:** M0 ✅ · M2 ✅ · M3 backend ✅ · **M4 in progress** · M5–M7 not started.

---

## 0. Immediate — the working tree

- [ ] ANY: **commit 79 uncommitted files.** M4.1 (`/records/existence` + tests), the
      `@pulseos/ui` extraction (11 files moved, 36 patient files repointed), the whole doctor
      portal, the regenerated api-client, this doc refresh. Suggested split: backend M4.1 /
      shared-ui extraction / doctor portal M4.2. Nothing else should start until this lands.
- [ ] ANY: add **`backend/.env.example`**. `backend/.env` is read relative to the process CWD
      (`make dev-api` runs from `backend/`), while the root `.env` is docker-compose only. The
      absence of an example is what makes that invisible; it has cost debugging time twice.

## 1. M4 — Core Features Complete (current milestone)

Ordered by dependency. Each item is demonstrable on its own.

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
      revoked, delivered through arq. Currently an empty `__init__.py`; access requests arrive
      silently.
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
- [ ] PO: Confirm the LLM provider and obtain an API key (Gemini per ADR-007) — needed by M5,
      earlier for experiments.
- [ ] PO: Resolve the Review-1 deck conflict — Spring Boot + Synthea (slide 20) vs ADR-001
      FastAPI + the 3-simulated-hospital plan. Amend the ADRs or fix the slide.
- [ ] ANY: Amend DOMAIN_MODEL.md §1 — its audit vocabulary is a strict subset of the
      implemented one (`ACCESS_DENIED` missing, ADR-018).

## 4. Testing debt

- [ ] FE: **no component or DOM tests exist.** All 131 web tests are pure logic (`view.ts`
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
- [ ] FE: Figma — the 3 core journeys (CONTEXT.md). *Note: the patient portal and the doctor
      slice were built without it, so this is now documentation of what exists as much as
      design of what will.*
- [ ] AI: Spike — Gemini free-tier limits vs expected summary/copilot volume.
- [ ] AI: Spike — EasyOCR vs Tesseract accuracy on 5 synthetic Indian lab-report PDFs.

## 6. Ops / demo readiness

- [ ] PO/ANY: run the full local stack once and keep it running: `make up`, `alembic upgrade
      head`, `scripts/seed.py`, both portals, a real Firebase login. Verify an upload lands in
      MinIO.
- [ ] BE: consider mapping database-connection failures to **503** (as Firebase and storage
      outages already are). Today a dead database is a 500 "An unexpected error occurred" with
      no CORS headers, which reads to a browser as a CORS bug. `/ready` already reports it
      correctly, so this is diagnosability, not correctness.
- [ ] BE: consider declaring `HTTPBearer(auto_error=False)` as a documentation-only dependency
      so OpenAPI emits `securitySchemes` and Swagger gets an Authorize button. Enforcement
      would not change; the spec currently under-documents that endpoints need credentials.

## Parking Lot (not now)

- Emergency QR security design (break-glass) — Phase 2, needs its own ADR.
- OpenAPI-driven contract tests between web client and backend (schemathesis).
- Synthetic medical-record generator for realistic seed/eval data (needed by M5 evals).
- Content sniffing (magic bytes) on uploads — currently trusts the declared content type after
  allowlisting; revisit in the M7 security pass.
- Per-hospital breakdown on `GET /records/existence` (SYSTEM_ARCHITECTURE:67 mentions it;
  shipped category-only because naming the organisations is a disclosure the patient has not
  consented to).
