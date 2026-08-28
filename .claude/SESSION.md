# SESSION.md — Session Log & Handoff Notes

> Newest entry first. Every Claude session appends an entry before ending.
> Format: date, what was done, decisions made, exact next step.

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
