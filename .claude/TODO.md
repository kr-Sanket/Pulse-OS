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

- [ ] FE: **doctor portal slice 2 — request access.** From the existence results, select
      categories and `POST /access-requests`; show `/access-requests/sent`. This closes the
      loop with the already-built patient consent inbox and makes the M3 gate demonstrable end
      to end for the first time. *Blocked by nothing — the backend is complete.*
- [ ] BE: **rate limiting** (Redis buckets, stricter on auth). Was deferred since M0.3 and is
      now load-bearing: `POST /access-requests` **and** the new `GET /records/existence` are
      both unthrottled Health-ID existence oracles (finding M3-D). Ship with or before slice 2.
      `GET /granted-records` needs the same bucket, though it is not an oracle: it answers only
      where a live grant already exists, and every probe without one writes an `ACCESS_DENIED`.
- [ ] BE/PO: **decide whether discovery is audited.** `GET /records/existence` writes no audit
      event — no record was accessed and no truthful `AuditAction` member exists. A doctor
      probing Health IDs is arguably something a patient should see. Adding a member is
      ADR-sized (ADR-018 is the precedent); a test currently pins the *absence*.
- [ ] BE: **local-dev identity script** (`scripts/dev_link_identity.py`) to attach a real
      Firebase UID to a seeded staff row, replacing the raw SQL currently needed to obtain a
      hospital-admin token. Must be loud, local-only and never importable by app code —
      `auth/seed.py` refuses to plant login-capable identities *on purpose*, so this walks
      around a deliberate guard and needs a conscious decision.
- [ ] BE: **no code path provisions `Role.SYSTEM_ADMIN`**, so `POST /hospitals/{hid}/verify`
      has no reachable caller and self-registered hospitals are stranded `PENDING`. Masked in
      demos because the three simulated hospitals are seeded `VERIFIED`.
- [ ] FE: **hospital portal** — `/hospitals/me`, upload for a Health ID, doctor list +
      activate/deactivate. Second data source, and the only UI for the ADR-015 endpoints.
- [ ] BE: **`notifications` module** — in-app notification on request created / decided /
      revoked, delivered through arq. Currently an empty `__init__.py`; access requests arrive
      silently.
- [ ] BE: **patient locker hide/unhide.** `is_hidden` is enforced on every non-owner read
      (including the new existence projection) but has no endpoint.
- [ ] FE: QR identity generation + scanning (ROADMAP M4 scope).

## 2. Deferred M3 review findings (backend)

Each is a stated security or correctness gap. **M3-D is now the most urgent** — see §1.

- [ ] BE: **M3-B (narrowed by ADR-020)** — `GET /records` returns full metadata and writes
      **no** audit event. SYSTEM_ARCHITECTURE rule 3 covers "metadata-beyond-existence";
      CHECKLIST:26 requires an entry for every read. The clinician half is now settled:
      `GET /granted-records` writes one `RECORDS_LISTED` per request, so the rule holds without
      exception for **non-owner** listings. What remains is the owner/hospital-admin case, whose
      argument is genuinely weaker (the caller is the subject, or the uploader) — so this is now
      a ruling on whether rule 3 should say "non-owner", not an unaudited clinician read.
- [ ] BE: **M3-E** — hospital-admin denials are unaudited (layer 2 refuses before the choke
      point) while clinician denials are logged. One ruling should settle this and the
      hidden-record refusal together.
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
- [ ] PO: Review ADR-015 and **ADR-016…019** — all implemented per their documented rationale.
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
- Hoist the shadcn UI kit into `@pulseos/ui` — do it when the hospital portal makes a third
  copy of the primitives.
- Per-hospital breakdown on `GET /records/existence` (SYSTEM_ARCHITECTURE:67 mentions it;
  shipped category-only because naming the organisations is a disclosure the patient has not
  consented to).
