# Changelog

All notable changes to PulseOS are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: milestone-based pre-1.0.

## [Unreleased]

*Newest batch first. The batch below is uncommitted working-tree work (2026-10-14/15), validated
locally only (SQLite and a disposable PostgreSQL 16.15); it has not run in GitHub Actions.*

### Security
- **Patient lookup requires a VERIFIED hospital.** `GET /patients/lookup` answers 409 to an
  administrator of a PENDING hospital, before the Health ID is parsed, so a self-registered
  account can no longer resolve Health IDs to names (ADR-021 amendment).
- **Clinician AI search is audited and rate-limited.** `GET /ai/patients/{patient_id}/search`
  writes one event per request — the new `RECORDS_SEARCHED` action, or `ACCESS_DENIED` with no
  granted scope — and has its own `ai_search` bucket (30 / 60 s). Query and record text are never
  stored (ADR-020 amendments 1 and 2). The query still travels in the URL query string.

### Added
- **`RECORDS_SEARCHED` audit action** for AI-assisted record searches, labelled
  "Records searched (AI)" in the patient and hospital audit views. No migration (`audit_logs.action`
  is `VARCHAR(32)` with no CHECK, verified on the migrated PostgreSQL schema); existing rows keep
  `RECORDS_LISTED`. OpenAPI spec and generated client regenerated.
- **PostgreSQL concurrency regression tests** (`tests/test_consent_postgres.py`, opt-in):
  concurrent duplicate request creation and concurrent approvals (each with a no-lock control),
  unique-versus-other integrity-error mapping, and the 255-character multibyte filename at the
  column; plus a migrated-schema check for `RECORDS_SEARCHED`. Added to the existing
  `backend-postgres` CI job's file list.

### Fixed
- **Duplicate consent requests and grants** now return 409 deterministically: a request for a
  category already actively granted, or already asked for on an open unanswered request, and an
  approval that would create a second active grant. Checks run under a per-(patient, clinician)
  PostgreSQL advisory lock; only UNIQUE violations map to 409.
- **Expired consent requests** — the PENDING → EXPIRED transition is now persisted (the refusal
  is returned rather than raised, ADR-017 amendment) and listings report a past-deadline request
  as EXPIRED. Expiry is still lazy; there is no sweep.
- **Upload file names over 255 characters** return 422 instead of failing at the database.
- **Backend lint and tests:** ruff format/lint findings in four test files added by `15b2d1b`;
  two `test_alembic_postgres.py` tests pinned to revision `0007` after 0008 moved `head`.

### Added
- **In-app notifications (`15b2d1b`, ADR-031).** Migration 0008 (`notifications`); notifications
  for access requested / approved / rejected / revoked written in the consent transaction with
  generic no-PHI text; `GET /notifications`, `GET /notifications/unread-count`,
  `POST /notifications/{id}/read`, `POST /notifications/mark-all-read` (patient and doctor);
  shared bell + drawer polling every 30 s in the patient and doctor portals.
- **Automatic consent/permission refresh (`5690a93`)** — polling and focus refresh on the patient
  consent inbox, grants and dashboard and the doctor sent-requests and granted-records screens.
- **Granted-category indicators (`13e2034`)** — the doctor portal marks already-granted
  categories and prevents re-requesting them; the AI assistant sits above the granted records.

### Changed
- **PostgreSQL host port defaults to 5433 (`72b55e2`);** the container still listens on 5432.
- **Experimental E2E work removed (`281439c`);** no E2E suite exists or is planned for the final
  review.
- **Documentation brought up to date with `72b55e2` (2026-10-14).** Status, roadmap and TODO
  reflect the pushed notifications work; ADR-031 marked Implemented with implementation notes;
  README separates the implemented local hash/Merkle integrity from the unbuilt Polygon anchoring;
  the five final-review priorities are recorded in ROADMAP.md and TODO.md.
- **Documentation aligned with the implementation (2026-10-11; lands with this change set).**
  AI, security, tech-stack, architecture, domain, database, development, API and status documents
  now describe what is built separately from what is planned. New ADR-028 (local Ollama as the
  sole provider; redaction revisited) and ADR-029 (lexical retrieval; pgvector deferred) record the
  Product Owner's direction; ADR-030 (Synthea FHIR import) is **proposed**. ADR-002, ADR-007 and
  ADR-008 carry status amendments; no historical decision text was rewritten. The documentation
  also records a found gap: AI retrieval did not honour hidden records (fixed in this change set;
  see Security).

### Added
- **Opt-in PostgreSQL CI job and migration tests (2026-10-11; lands with this change set).** A
  `backend-postgres` GitHub Actions job runs the opt-in PostgreSQL tests against a disposable
  PostgreSQL 16 service and fails if any is skipped; `tests/test_alembic_postgres.py` covers
  migration 0007 upgrade, model parity, CHECK enforcement and downgrade on a fresh database per
  test. The job has **not yet run on GitHub**.
- **Audit integrity M6.1–M6.3 (`e3c0fe1`, `1ce4c14`, `155cbf1`, 2026-10-11).** v3 audit digests
  use Ethereum Keccak-256 (v1/v2 SHA-256 rows still verify); deterministic Merkle trees and
  membership proofs; batch commitments; migration 0007 (`audit_batches`, `audit_batch_members`);
  transactional batch sealing with conflict classification; database-only reconciliation including
  unbatched-event integrity checks; v3 events refused by per-event anchoring; opt-in PostgreSQL
  integration tests. ADR-027 accepted; ADR-019 resolved. **Nothing is submitted to any chain**;
  M6.4 is not authorized.
- **AI layer (`a7df8b4`…`ff5b3fe`, 2026-10-04 to 2026-10-08).** Deterministic FHIR ingestion into
  `ai_documents`/`ai_chunks` (migration `aedb0169a4eb`); consent-scoped lexical retrieval;
  context assembly; the `AnswerGenerator` protocol; a clinician AI assistant
  (`/ai/patients/{patient_id}/search`, `/answer`) and patient Health Copilot (`/ai/me/answer`)
  with the `ai_generate` rate limit and `SUMMARY_GENERATED` audit events; doctor and patient
  portal panels.
- **Audit anchoring foundation (`b17c2f0`, 2026-10-04).** `AuditAnchor` port,
  `LocalChainAuditAnchor` (network-free simulation), migration 0006 (`audit_anchors`), and
  `GET /audit-logs/{audit_log_id}/verification`.

### Removed
- **Gemini provider (`c95494a`, 2026-10-10).** Local Ollama (Qwen3:8B) is the only supported
  generation provider (ADR-028).

### Security
- **Doctor-facing AI retrieval excludes patient-hidden records (2026-10-11; lands with this change
  set).** Clinician search and answer generation filter `is_hidden` in the database query, before
  scoring and the result limit. Hidden records no longer reach clinician results, generation
  context or citations. Hiding and unhiding take effect without re-indexing. The patient's own
  copilot is unchanged and still includes their hidden records. Regression tests passed locally
  on SQLite and on a disposable PostgreSQL 16.15; GitHub CI has not run on it. Still open: the
  clinician search endpoint is neither audited nor rate-limited (SECURITY.md).

### Added
- **Patients can hide and unhide their own records** — `PATCH /api/v1/records/{record_id}/visibility`.
  The `is_hidden` column has existed since migration 0003 and every read layer has enforced it
  since M3; what was missing was any way for a patient to set it. This is that, and only that:
  no migration, no new column, no change to a single enforcement rule.
  **Any record the patient owns, whatever its origin.** The RBAC matrix read "own locker only",
  which was ambiguous and, taken literally, would have gated the *write* by origin while
  `_authorize_read` and both grantee queries test the flag and never look at origin — one flag
  with two rules, and a patient unable to predict which of their records carries the control.
  DOMAIN_MODEL §1 and §3 now say "own records". The demo corpus is unaffected either way (all
  890 imported records are `PATIENT_LOCKER`), but a hospital upload is now hideable, which is
  the case worth demonstrating.
  **A sub-resource, not a PATCH of the record.** A filed clinical record is immutable — nothing
  can move, retitle or delete it — and `PATCH /records/{id}` would announce the opposite, with
  the next field added to its request model silently becoming a mutable clinical field.
  `isHidden` is the patient's preference *about* a document rather than a property of it, and
  the URL says which. The body is one required, non-nullable boolean, so there is no partial
  form of the request and no `Unset` sentinel: an empty body, an explicit `null` and an unknown
  key are all 422. It is `StrictBool` rather than `bool`, which departs from Pydantic's default
  coercion on purpose — in lax mode `"yes"`, `"on"` and `1` all mean `True`, and inferring a
  privacy setting from a wrong-typed value is worse than refusing it.
  **Ownership is the signature, not a check.** The patient row is resolved from the token and
  compared against `record.patient_id`; no path, query or body parameter names a patient. Another
  patient's record and a record that does not exist return the same 404 with the same body, byte
  for byte, so the endpoint is not an oracle for which record ids are real — asserted by equality
  of the two responses, not merely of their statuses. Every non-patient role is refused by the
  role gate before any lookup happens, so a doctor holding a live grant can read a record and
  still cannot un-hide one.
  **Hiding is not revoking, and the tests are where that distinction lives.** After a hide, the
  grant keeps its status, categories and expiry; `grantedCategories` still reports the approved
  scope beside an emptied page; the row, the S3 key and the file are untouched; and unhiding puts
  everything back. What does change is every grantee path at once: the record leaves
  `/granted-records`, its category leaves `/records/existence` once it is the last non-hidden one
  there, and both the metadata read and the download answer 404.
  **No audit event**, for the reason the profile-edit slice gave: `AuditAction` has no member
  that states an owner's own visibility change truthfully, and the trail exists to hold *other*
  parties accountable to the patient. `RECORD_VIEWED` would invent a read and `CONSENT_REVOKED`
  would assert a withdrawal the `consent_grants` table contradicts. A test counts `audit_logs`,
  `consent_requests` and `consent_grants` across three toggles and asserts all three are
  unmoved — so routing this through `consent.enforce` later fails loudly rather than quietly.
  **One limitation, stated rather than hidden:** a presigned download URL issued *before* a
  record was hidden stays valid until it expires (`s3_presign_ttl_seconds`, 300s by default).
  Hiding stops new URLs being minted; it cannot recall a signature already given.
  In the patient portal, a "Hidden" badge appears on both the record card and the details panel,
  and the action — "Hide from doctors" / "Unhide" — lives only on the panel, where a record's
  other actions already are: a privacy control repeated down a 25-row list is a mis-click
  waiting to happen. No confirmation dialog (it is reversible by the button that replaces it),
  no toast, server-confirmed rather than optimistic, and the confirmed record is applied through
  an id-keyed overlay — the same device `applyRevocations` uses on the grants page — so the panel
  stays open, the cursor holds and nothing "Load more" has appended is lost. The explanatory line
  names the exception instead of over-promising: the uploading hospital keeps its ADR-013 layer-2
  access to its own upload.
  `isHidden` joins `RecordMetadataResponse`, which the doctor and hospital portals also consume;
  neither renders it, and `GrantedRecordResponse` deliberately does **not** gain it — for a
  grantee the value could only ever be false, and the existing chooser-allow-list test already
  named `isHidden` among the fields it must never carry. 43 new backend tests (653 total, 97%
  coverage held) and 13 new web tests (463 total).

### Added
- **Patients can edit their own profile** — `PATCH /api/v1/patients/me`. The Edit Profile
  button had been a deliberate placeholder because the API had no `PATCH` or `PUT` endpoint
  anywhere; this adds the first one. Three fields are editable, and only three, because they
  are the whole of what `patients` stores about a person beyond their identity: `fullName`,
  `dateOfBirth` and `gender`.
  **Partial semantics, with clearing distinguishable from omission.** An absent key means
  "leave alone" and an explicit `null` means "clear" — `None` cannot carry both for a
  nullable column, so an `Unset` sentinel carries the difference from the request model
  through to the service and no layer has to consult a set of field names. An empty body is
  a 422 rather than a 200, because answering success to a request that named no field would
  report an edit that did not happen.
  **Ownership is the signature, not a check.** The row is resolved from the authenticated
  `user_id`, and no path, query or body parameter names a patient — pinned by a test
  asserting the operation declares no parameters at all. The Health ID, Firebase UID, role,
  status and `createdAt` are unreachable rather than merely undocumented: `RequestModel`
  forbids unknown fields, so naming one is a 422, asserted alongside a follow-up read
  proving nothing moved. Registration and editing now share one set of validators, so a
  value that could not be registered cannot be reached by editing either.
  Email and Health ID render as read-only text rather than disabled inputs — a greyed-out
  box reads as a control that broke, not as a fact that cannot change.
  **No migration** (every column exists and `updated_at` already auto-stamps) and **no audit
  action**: a profile edit is not access to a record, and `AuditAction` has no member that
  would state it truthfully. The name a hospital verifies against at `/patients/lookup` is
  therefore self-editable and unlogged — accepted for Review-1, and revisited when the
  deferred operational audit log lands.
  A Synthea regression test covers the imported-patient case: editing an imported patient's
  name, date of birth and gender leaves every one of their records, their patient id, Health
  ID and owning user untouched, and writes no consent or audit rows. 32 new backend tests
  (610 total, 97% coverage held) and 13 new web tests.

### Fixed
- **The patient's audit trail attributed events to where the actor works *now*.** The page
  read `StaffDisplayResponse.hospitalName`, which the staff projection resolves by joining
  `doctors.hospital_id` — the present-affiliation join ADR-023 exists to refuse, arriving by
  a different route. A clinician changing employer silently re-attributed every past access
  in the patient's trail to their new hospital. It now reads `actorHospital`, resolved from
  the `actor_hospital_id` recorded on the event itself (**ADR-025**). The regression test is
  the whole decision in one assertion: an event written at hospital A by a doctor who now
  works at hospital B reports **A** as the hospital and **B** as the actor's employer, on the
  same row — it can only pass if the two come from different sources.

### Added
- **Audit History is grouped hospital → actor → events**, newest first at every level, with
  per-group event counts, latest activity in each header, and expand/collapse. The most
  recent hospital and its most recent actor open by default; everything else starts closed,
  and the reader's choices then stick — pages loaded later never reopen a group they closed.
  Two groups are deliberately **not** hospitals and say so: *Your own activity* (a patient
  belongs to no organisation) and *Unattributed activity* (events predating migration 0005),
  the latter carrying the reason. Neither is merged into a hospital and no hospital is
  inferred for them — on live data the same clinician correctly appears in two groups, 20
  events attributed to TMH and 34 unattributed.
  **Grouping is a rearrangement, never a filter**, and a test asserts it: every visible event
  appears exactly once and group counts sum to the input. Filtering runs *before* grouping,
  so the own-activity toggle cannot leave a group counting hidden rows, and a group whose
  events are all filtered disappears rather than rendering empty.
- **Cursor-based Load more on the audit page.** The endpoint has always been paginated; the
  page never sent a cursor, so the trail stopped at its first page — and once collapsed, a
  group would have looked complete when it was not. Counts are labelled as covering the
  events loaded so far: the API publishes no lifetime total, and presenting a page total as
  one would misstate a compliance record.
- `AuditEventResponse.actorHospital` (`{hid, name}`, nullable) and
  `StaffDirectoryService.hospitals_by_id`. `StaffDisplayResponse` is **unchanged** and keeps
  its current-affiliation meaning — "where does this person work now" is the right question
  in the consent inbox and the wrong one in a historical log, and ADR-025 splits the two
  rather than replacing one. No migration (the column and its index landed in 0005), no new
  audit event, no hash change, no authorization change; `HospitalAuditEventResponse` did not
  gain the field, pinned by test.

- **Record listings were ordered by import time, not by when care happened.**
  ``created_at`` defaults to the transaction clock, so every record written in one
  transaction shares an instant and ``ORDER BY created_at DESC, id DESC`` collapsed onto
  the random UUID tie-breaker. Measured on the imported demo patient: **103 records, one
  distinct ``created_at``, 39 distinct ``date_of_service`` spanning 1963 to 2018** — the
  first page read 2016, 2010, 2013, 2016, 2009, 2017, 1996, 2015. Both record listings now
  order by ``date_of_service`` with ``id`` as the tie-breaker. The bulk import only made
  this visible; any multi-record write had it.
- **The patient's Medical Records page could not reach past its first 100 records.** It
  asked for the API maximum, never sent a cursor, and rendered ``nextCursor`` as a static
  "older ones are not listed yet" line — so 3 of the demo patient's 103 were unreachable
  and its search covered only what happened to be loaded. The page now asks for 25 and has
  a Load more.

### Added
- **Sort, search and reset on ``GET /api/v1/records``.** ``sort=newest|oldest`` over the
  clinical date, and ``search`` as a case-insensitive substring of the filename or
  description. Both are server-side, because the page holds one page at a time and anything
  decided in the browser could only ever filter a slice of the history.
  LIKE metacharacters in a search term are **literal**: a patient looking for ``100_mg`` or
  ``50%`` means those strings, so the term is escaped and the escape character is escaped
  first (escaping it after ``%`` and ``_`` would double the escapes just introduced).
  A new ``DateCursor`` carries ``(sort, date_of_service, id)`` alongside the existing
  ``CursorKey``, which four modules use unchanged. Two properties it exists for:
  ``date_of_service`` is **not unique**, so the id half of the keyset is load-bearing rather
  than decorative — a page boundary landing inside a same-date run would otherwise skip it
  or serve it twice; and a cursor names a position in *one* sequence, so one issued under
  the other sort is **refused with 422** rather than honoured, which would have returned a
  page from the wrong end with no error. Verified against the live corpus: walking all 103
  records in both directions at three page sizes yields 103 rows, 103 unique, correctly
  ordered.
  **``/granted-records`` gains the ordering fix and nothing else.**
  ``GrantedRecordResponse`` deliberately withholds ``originalFilename`` and ``description``,
  and a search over exactly those two withheld columns would turn the clinician listing into
  an oracle for them — result counts would recover a diagnosis-bearing description one
  substring at a time. Sorting discloses nothing the page does not already show; searching
  would. Pinned by two regression tests and the existing exact-parameter-set assertion.
  18 new backend tests (573 total, 97% coverage held) and 5 new web tests (425 total). No
  migration: the plan is `Bitmap Index Scan` on the existing ``patient_id`` index feeding a
  top-N heapsort over one patient's rows, 0.36 ms at 890 rows, so a composite index would be
  speculative — the trigger is recorded in TODO instead.

### Added
- **Synthea FHIR R4 import** (`app/modules/records/fhir_mapping.py`, `fhir_import.py`,
  `scripts/import_synthea.py`) — ten pinned synthetic patients with **889 real clinical
  records** between them, so the portals show a clinical history instead of an empty locker.
  Verified end to end against live Postgres + MinIO: 889 rows created, a re-run creates 0,
  and a presigned download returns byte-exact FHIR JSON.
  **Three premises were checked against the data rather than assumed, and two were wrong.**
  `Bundle.type` is `transaction` with no `meta.fhirVersion` anywhere; references are
  `urn:uuid:` matching `entry.fullUrl`, **not** `Patient/{id}`, so resolution is
  bundle-local; and `Patient.id` differs from the Synthea business identifier in 1,180 of
  1,180 bundles. The canonical patient key is
  `identifier[system=…/synthea].value`, verified unique across all 1,180 and identical to
  both the filename UUID and the MRN in every one.
  **Observations fold into the DiagnosticReport that claims them** (343 of the canonical
  patient's 443 have such a parent), which is clinically right — a lab panel is the
  document, its analytes are results — and takes that patient from 589 rows to 103.
  Encounters are a grouping key, `Claim`/`ExplanationOfBenefit` are billing noise; neither
  becomes a record.
  **Idempotent by construction, not by bookkeeping:** the patient keys on a derived
  `synthetic:patient:synthea:{id}` subject and each record on a UUIDv5, so the derived
  `s3_key` collides on re-import and the UNIQUE constraint is what refuses the duplicate.
  A `uuid4()` here — as the upload path uses — would have doubled every row on the second run.
  **Consent-neutral.** It writes `medical_records` rows and objects, and nothing else: no
  grant, no request, no audit event (0 of each for all ten imported patients on the live
  database). Imported records enter the consent model exactly as uploaded ones do, because
  `consent.enforce` keys on `(patient_id, category_id)` and never reads `origin` — so the
  fear that ~900 rows become readable by any clinician merely by existing is answered by
  eight tests over records that actually came out of the importer.
  `origin` is `PATIENT_LOCKER` with both `uploaded_by_*` NULL (OD-S1). Attributing them to
  a hospital would have handed that hospital ADR-013 layer-2 own-upload read access — a
  consent bypass dressed up as a data-modelling shortcut.
  **Prohibited identifiers are unrepresentable, then independently asserted absent.** Every
  Synthea `Patient` carries a synthetic SSN, most a driver's licence and passport, plus a
  foreign MRN and a phone number. The scrubber keeps an allow-list of one identifier system
  and drops `subject`, every `reference` and every narrative `div`; then each object is
  scanned for that patient's own secrets before it is stored, and an import that cannot
  prove an object clean fails instead of proceeding. **All 889 objects were fetched back out
  of MinIO and re-scanned: zero leaks.**
  SNOMED/LOINC/RxNorm coding is preserved inside the stored object — the one thing that
  cannot be recovered later without re-importing, and what M5's retrieval layer will need.
  Raw FHIR lives in object storage rather than a JSONB column: it needs no migration, makes
  Download meaningful, and stays behind the audited consent-checked `download-url` path. A
  JSONB column remains deferred and **needs its own ADR** — ADR-006 explicitly declines to
  run a FHIR server, and the "hybrid storage" plan exists only in a Review-1 slide.
  Three seeded categories added — `CONDITION`, `PROCEDURE`, `ALLERGY` — as **rows in a
  seedable table, so no migration and no frontend change**: the portals fetch the vocabulary
  and render unknown codes as themselves. **No schema change, no API change, no client
  regeneration, no frontend change.** 58 new backend tests (555 total, 97% coverage
  maintained); fixtures are committed and hand-trimmed because the 1.3 GB corpus is
  gitignored and no test may depend on it.

### Changed
- **One shared login experience across the three portals** (`@pulseos/ui/src/components/AuthShell.tsx`).
  The three login pages were near-identical hand-written copies — the doctor's and the
  hospital's differed only in two sentences, and the patient's had never been moved onto the
  design system at all (inline `fontFamily`, raw `<h1>`/`<button>`, the only page in the repo
  off the token set). Same hoist the primitives got, for the same reason. A full-page teal
  gradient, a rounded split container at `md`, brand panel with the existing `HeartPulse` mark
  plus a new inline-SVG artwork at `lg`, and a white authentication panel with a centred
  "Welcome!". Each portal keeps only its name and its one line of copy, in a new
  `src/login/view.ts`.
  **No authentication semantics changed.** Still `signInWithPopup` with a `GoogleAuthProvider`
  behind `auth/provider.ts`; every file under `src/auth/` except the new hook, both
  `ProtectedRoute` and all three `App.tsx` are byte-identical to before. PulseOS has no
  credential mechanism, so the design's email/password affordances were deliberately **not**
  built: no email field, no password field, no reset, no remember-me, no credential sign-up.
  `describesNoCredentialFlow` in each `view.ts` asserts that in a test, so the copy cannot
  start describing a flow no code path implements.
  **Two WCAG AA fixes measured, not assumed.** Near-white text on `--primary` is 3.99:1, short
  of AA for normal text — a token-level shortfall affecting every primary button in all three
  portals. The brand band and the login CTA are deepened locally with `color-mix`, taking all
  13 text/background pairs on the page to AA (worst case 4.74:1); `--primary` itself and the
  `Button` primitive are untouched, so the underlying gap remains open for its own slice.
  Both CTA backgrounds carry `!` because Tailwind v4 emits arbitrary-value utilities *before*
  named ones, so `bg-primary` from `buttonVariants` would otherwise win on equal specificity
  and the override would compile and do nothing — confirmed against the built stylesheet.
  15 new pure view tests (420 web tests total); no DOM-testing infrastructure added.
- **The shadcn primitives are now shared** (`@pulseos/ui/src/components/ui/`), taken out of both
  portals before the hospital portal made a third copy — the trigger TODO.md had recorded. All
  nine primitives the two portals both held were **byte-identical**, so this is one
  implementation promoted, not a merge: `avatar`, `badge`, `button`, `card`, `dialog`, `input`,
  `label`, `separator`, `skeleton`, plus patient-only `select`/`switch` and doctor-only
  `checkbox`/`textarea`, 13 in total. 69 files repointed to the barrel; `@/components/ui/*` no
  longer resolves in either app. The apps' `components.json` moved to the package so
  `shadcn add` cannot silently recreate a duplicate, and the primitives' `cn` import became
  relative — a `@/` path inside a shared package resolves against the *consuming app's* `src`,
  which is the one way this refactor could have broken at runtime.
  **Each app now needs `@source "../../../packages/ui/src"` in its `index.css`:** Tailwind v4
  scans files rather than the import graph and skips `node_modules`, where pnpm's workspace
  symlink puts the package — without that line every primitive renders unstyled.
  Behaviour-neutral, and measured as such: 249 web tests unchanged, both JS bundles unchanged
  in size with each portal's `data-slot` inventory proving the unused primitives tree-shake
  out, and a per-rule diff of the generated CSS showing **zero rules removed or altered** in
  either portal. The CSS grows (+1.7 kB patient, +9.1 kB doctor, uncompressed) purely by
  additions for primitives that portal does not yet render — the cost of scanning one shared
  directory instead of two divergent ones.

### Added
- **`scripts/dev_link_identity.py`** — the local-development identity linker TODO §1 asked
  for, replacing the hand-written SQL previously needed to sign in as a seeded hospital
  admin. It rewrites `users.firebase_uid` on **one already-seeded row** and stamps the
  PulseOS claims through the auth module's own port; it creates nothing, deletes nothing,
  and never chooses a role — the role comes from the row that already exists, so there is
  no flag that could provision one.
  **Two independent safety checks, neither reachable by a flag:** `PULSEOS_ENVIRONMENT`
  must be exactly `local`, *and* the database host must be this machine. The second exists
  because the first fails open — `Settings.environment` defaults to `local`, so a
  deployment that forgot to set it would look like a laptop, whereas the database it points
  at cannot be faked by forgetting something. There is deliberately no `--force`; `--yes`
  only skips the confirmation prompt, and a test asserts no `force` flag exists.
  Claims are provisioned **inside the same transaction** as the row change, mirroring the
  invariant registration already holds, so a provider failure rolls the link back rather
  than leaving an account half-linked. `--skip-claims` covers the no-Firebase-credentials
  case, and `--list` shows what is linkable.
  It can additionally correct the PulseOS profile of an identity it has linked —
  `--full-name` and `--email`, **HOSPITAL_ADMIN only** — because linking deliberately
  changes `firebase_uid` alone, which left a real developer signing in behind the seeded
  demo name "Ravi Prasad (Demo Admin)". Four rules keep that from becoming a profile
  editor: the flags require `--firebase-uid`; the row must already be, or be becoming in
  the same run, that UID's identity; patient and doctor rows are refused outright; and
  there are two fixed fields with no `--set`. The Firebase account is never written to —
  external authentication identity and domain profile data stay separate, which is the
  distinction the mismatch tempted us to collapse. Because `--email` mutates the column
  `--user-email` looks up by, resolution now also accepts `--firebase-uid`, and an email
  already held by another `users` row is refused rather than creating an identity nothing
  can unambiguously name. **No reverse operation is offered:** restoring
  a seeded subject is a destructive edit to a row a real account is signing in with, so it
  is left to its own slice rather than bundled in here.
  **Known hazard, documented rather than worked around:** a seeded row carrying a real UID
  is invisible to
  `scripts/seed.py`, which then inserts a duplicate user *and* a duplicate hospital-admin
  row for the same hospital (`hospital_admins.hospital_id` carries no unique constraint) —
  a hazard the old SQL workaround left completely unguarded and one this script documents
  rather than silently works around. Backend tests 390 → 432.
- **Rate limiting on the Health-ID and discovery surfaces (ADR-024, closes finding M3-D).**
  Four endpoints were unthrottled, one of which returns a patient's **name**; ADR-012 chose
  random Health IDs to defeat enumeration, and without a limiter that defence was half-built.
  Now: `patient_lookup` 20/60s, `record_existence` 30/60s, `granted_records` 30/60s,
  `access_request_create` 10/60s, keyed on the caller's PulseOS `user_id`.
  **A per-route dependency, not middleware — and the guideline was wrong.** API_GUIDELINES
  said "per user at the middleware layer", but Starlette middleware runs before routing and
  dependency resolution, so no authenticated user exists there; the two halves of that
  sentence cannot both hold without verifying the token twice per request. `rate_limited()`
  sits in `auth/dependencies.py` beside the role gates, and the guideline is amended.
  Order is authenticate → authorize → limit → service, which buys three properties: the
  subject is a verified identity, a caller refused by the role gate spends nothing, and **the
  limiter runs before any Health ID is resolved**, so a 429 cannot vary with whether a patient
  exists. **Every outcome spends quota** — a 404 costs the same as a hit, because probing an
  ID that matches nobody is exactly the request an attacker makes.
  Fixed window, `INCR` + `EXPIRE NX` in one pipeline: `INCR` is atomic and returns the
  post-increment value, so the read-then-write race cannot occur, and the window index is
  part of the key, which turns a lost TTL into a bounded memory leak rather than a lockout.
  `Retry-After` is arithmetic, not a second round trip. **Fail-open**, following ADR-014's
  precedent that Redis is advisory here — a blip must not take consent requests offline — with
  the outage log throttled to one line per 30s.
  The 429 body is identical for every bucket and caller: no bucket name, no counts, no Health
  ID. Declared in OpenAPI on exactly the four protected operations (the only spec diff; no
  schema added, no parameter added). Configuration is two variables, and malformed limits
  raise at **startup** rather than per request — a limit that silently fell back to a default
  because of a typo is a security control that lies.
  **Explicitly not covered:** unauthenticated/pre-auth throttling, which needs IP keying and
  therefore trusted-proxy semantics; `X-Forwarded-For` is client-controlled and is not
  trusted. Deferred to ADR-009. Backend tests 461 → 497.
- **Hospital portal — Slice 6c, the audit history page.** `/audit` in the hospital portal,
  over 6b's `GET /hospitals/me/audit-logs`, in the portal's usual layering
  (`audit/{api,view,useAudit}` + dumb components). Reachable whatever the hospital's
  verification state — reading what was recorded is not an operational action — and the page
  gates on nothing, loading no hospital profile at all: the one thing it would learn (no
  admin profile) is something the audit endpoint already says for itself with a 404.
  **The first real pager in the project.** Every other listing asks for a hundred rows and
  admits the truncation in a footnote; a compliance view is the first place where "and the
  rest is not shown" is not good enough. The hook accumulates pages, echoes the opaque
  cursor back and never constructs one, de-duplicates on id, and guards concurrent loads
  with a ref rather than the busy flag — which settles a render late, and would append a
  page twice. It is kept local, not promoted: one screen needs it, and a pagination hook
  designed against a single caller would be a guess at the second one's needs. A failure
  *after* the first page leaves the loaded rows on screen rather than replacing a compliance
  view with an error.
  **The response is treated as the whole truth.** Nothing fetches the record behind a row to
  enrich it: that would re-disclose precisely what 6b's allow-list withholds, and would write
  a `RECORD_VIEWED` to the patient's trail for every row rendered. A record target shows a
  short handle and no description; an absent one shows nothing rather than a placeholder. The
  actor is a name, falling back to a role — never a user id. An action this build does not
  recognise renders as "Audit event" rather than its raw code, and the row is still shown,
  because dropping an audit entry is not an option.
  The page states what the log does **not** cover (listings, Health-ID lookups, doctor
  activation, registration are all outside the patient-subject trail per ADR-022/023), and
  the empty state says no activity was *recorded* rather than that no records were accessed —
  the log knows what it captured, not what happened. Web tests 376 → 405. Frontend only: no
  backend, schema, migration or OpenAPI change, and the generated client already carried the
  endpoint from 6b.
- **Historical hospital attribution and a versioned audit-hash scheme (ADR-023, migration
  0005).** Hospitals had audit *events* after 6a but no way to read them: `audit_logs` carried
  no hospital, and the only alternative — joining the actor's **current** affiliation — would
  have moved history whenever staff transfer, migrating a doctor's past events into whichever
  hospital they joined next. `actor_hospital_id` is therefore captured at write time and
  passed as an argument, never looked up; it is **nullable** because patients generate a large
  share of events and belong to no hospital. There is a test that re-registers a clinician at
  a second hospital and asserts their earlier events stayed put.
  **`hash_version` selects the whole scheme — canonicalization *and* algorithm.** v1 is
  revision 0004's payload under SHA-256, v2 adds the new field, and **v3 is reserved for
  ADR-019's keccak transition**, which now has a mechanism to land in rather than invalidating
  the table. v1 **omits** the key rather than emitting it as null, which is exactly why every
  legacy digest still reproduces; one `canonical_event_payload` serves writing and verifying,
  so a verifier cannot drift from the writer. The version sits outside the hashed payload
  safely: a mis-selected scheme changes the key set and so fails verification in both
  directions, which is tested. Legacy rows keep NULL attribution and their original digests —
  no backfill, because the only source would be the forbidden join.
  New: `GET /api/v1/hospitals/me/audit-logs`, HOSPITAL_ADMIN-only, cursor-paginated, **with no
  hospital parameter at all** — the scope comes from the caller's admin profile, so no query
  string can reach another hospital. Its response is a separate allow-list from the patient's:
  **no `patientId`** (a hospital reads its own activity, not a roster of the people it
  touched), no digest or `hashVersion` (tamper evidence is published to the *subject* of a
  trail), nothing clinical.
  Still deferred, and now for one shared reason: the hospital record *listing* event and
  audit for `/patients/lookup` and `/records/existence` all need an organisation-scoped
  operational log, because a listing spans many patients and a failed probe has none —
  neither fits a NOT NULL `patient_id`. `patient_id` was **not** relaxed; the patient log
  keeps its meaning and simply gained a second truthful scope over the same rows.
  Backend tests 442 → 461.
- **Audit emission policy, and the events that were missing (ADR-022).** Investigating the
  hospital audit view found that hospital admins emitted **nothing**: `_authorize_read`
  returns at ADR-013 layer 2 *before* `consent.enforce`, so neither allowed nor refused
  hospital reads were recorded (finding M3-E), and `RECORD_UPLOADED` had sat in
  DOMAIN_MODEL §1's vocabulary since M0.2 and in `AuditAction` since M3 **with no writer at
  all** — a document could enter a patient's history leaving no trace of who put it there.
  Now emitted: `RECORD_UPLOADED` on every upload (hospital *and* patient locker — the
  vocabulary is unqualified, and a trail recording only one would lie by omission about the
  other), and `RECORD_VIEWED` / `RECORD_DOWNLOADED` / `ACCESS_DENIED` on hospital-admin
  reads. The *decision* stays in `records`, which alone knows who uploaded what; what
  changed is that both outcomes reach the trail, ending an asymmetry where a clinician's
  refused read was visible to the patient and a hospital's was not.
  **M3-B is ruled:** SYSTEM_ARCHITECTURE rule 3 means *non-owner* — a patient listing their
  own records is not audited, because logging the subject reading their own index grows the
  trail without bound while saying nothing about access. The hospital *listing* is a genuine
  non-owner read and still cannot be expressed: its page spans many patients while
  `audit_logs.patient_id` is singular and NOT NULL.
  Deferred with reasons recorded rather than rediscovered: patient lookup (NOT NULL
  `patient_id` means only *successful* probes are recordable, so the log would miss the
  enumeration it exists to catch); doctor activate/deactivate and hospital registration
  (no patient subject at all — administrative events that do not belong in a patient-visible
  trail).
  `records` gains a fourth seam, `RecordAuditor`, with two purpose-named methods rather than
  one general "write an event", so it cannot reach the rest of the vocabulary. The audit
  write sits inside the upload transaction after the object store succeeds, so a failed
  upload leaves no event. **No schema change, no migration, no index, no `event_hash`
  change.** Backend tests 432 → 442.
- **Hospital patient lookup, and upload confirmation (ADR-021).** New backend endpoint
  `GET /api/v1/patients/lookup?healthId=`, owned by the `patients` module, HOSPITAL_ADMIN-only,
  answering `{healthId, fullName}` and nothing else — the RBAC matrix row that had never been
  built (docs/DOMAIN_MODEL.md §3, "existence + name confirmation only"). It closes the safety
  gap Slice 3 shipped with: `POST /records` files a document against a Health ID, no endpoint
  edits or deletes a record afterwards, and an administrator had no way to check whose history
  they were about to write to.
  The service validates with `is_valid_health_id` **before** it queries, so a mistyped ID is
  refused as malformed rather than as "no such patient" — ADR-012's check character doing the
  offline typo detection it was specified for, and two genuinely different instructions to the
  person at the desk. No new table and no new repository method: `get_by_health_id` already
  existed. `/records/existence` is untouched — still DOCTOR-only, still presence-only, pinned
  by a contract test.
  In the hospital portal the upload page becomes two steps: find the patient, tick "I confirm
  this is the intended patient", *then* the document form opens. The confirmation is a value
  in a pure state machine (`patient-lookup/view.ts`), so the rule that matters — **a
  confirmation dies with the Health ID that earned it** — is one tested function rather than
  four setState calls that have to be read together. Editing the ID by one character, a failed
  lookup, or starting a new search all clear it; re-typing the same ID in a different case
  does not. `useRecordUpload.submit` takes the confirmed patient as an argument rather than
  reading it from anywhere, so uploading for an unconfirmed patient is unrepresentable.
  The receipt now names the patient, sourced from the lookup — `POST /records` returns no
  patient and was **not** widened to add one. PENDING hospitals stay blocked exactly as
  before, and outrank every other blocker in the new `uploadBlockedReason` gate.
  Backend tests 368 → 390; web 346 → 375. api-client regenerated: the spec diff is exactly one
  path and one schema, with zero drift elsewhere.
- **Hospital portal — Slice 4, uploaded records.** `GET /records` (server-scoped for a
  HOSPITAL_ADMIN to that hospital's own uploads, ADR-013 layer 2), `GET /records/{id}` and
  `POST /records/{id}/download-url`, in `uploads/{api,view,useUploads}` with dumb components
  and a detail page at `/uploads/:recordId`. Server order is preserved rather than re-sorted —
  a partial page re-sorted by service date would put an old record on top and imply it was the
  most recent thing the hospital uploaded. An empty page is its own outcome variant, so an
  empty list can never be rendered, and a `nextCursor` produces the same truncation note the
  other portals use.
  **The listing cannot say whose record a row is, and says so rather than faking it.**
  `RecordMetadataResponse` carries no patient identifier of any kind — verified against the
  generated schema — so both screens carry one sentence attributing the absence to the API
  instead of leaving a reader to read it as a missing column. This is the gap that makes
  after-the-fact confirmation of a Slice 3 upload impossible, and it is a backend question, not
  a UI one.
  The 404 wording names neither "no such record" nor "another hospital's record", because the
  API conflates them deliberately and naming one would confirm the other.
- **The record vocabulary and the download state machine moved into `@pulseos/ui`.** Origin,
  uploading hospital, file type, processing state and the whole `RecordMetadataResponse` →
  detail-view mapping now live in `lib/records.ts`; `DownloadState`, `POPUP_BLOCKED` and the
  two decisions behind the button live in `lib/download.ts`. A record does not change meaning
  with its reader — the doctor portal reads what a patient consented to share, the hospital
  reads what it uploaded, and both are looking at the same response — so one document
  described two ways by two PulseOS screens would be a defect, not a nuance. The doctor
  portal's `record/view.ts` is now re-exports; its 124 tests pass untouched.
  `canStartDownload` and `downloadOutcome` are functions rather than inline conditions
  specifically so the duplicate-click guard is unit-testable without a DOM: the server records
  a download when it *issues* the link, so a second click writes a second entry on the
  patient's trail for one intention, and a `disabled` attribute alone cannot prevent it
  because it only settles on the next render. Both portals' hooks now share them.
- **Hospital portal — Slice 3, upload for a Health ID.** The hospital half of
  `POST /api/v1/records` (multipart), in `upload/{api,view,useRecordUpload}` with dumb
  components: Health ID, file, category, date of service, optional description, then a receipt
  naming the patient the document was filed against.
  **The Health ID is the whole risk surface here, and the UI is built around that.** A hospital
  administrator cannot look a patient up — `/records/existence` is DOCTOR-only — and no
  endpoint edits or deletes a record afterwards, so a well-formed ID belonging to the wrong
  patient is unrecoverable from this portal. The field therefore leads the form, carries a
  standing caution to read the ID back from the patient's card, and the receipt repeats the ID
  rather than redirecting away. Shape validation matches the doctor portal's — prefix, year,
  seven characters — and deliberately stops short of ISO 7064, which lives once in
  `patients/health_id.py`; a test pins that a wrong check character passes locally and is left
  to the server's 422. A PENDING hospital gets the form disabled with its verification notice
  instead of a 409 after the file has been transferred, and each of the eight failure statuses
  is worded as something a receptionist can act on.
- **`toFormData` and `todayIsoDate` promoted into `@pulseos/ui`.** Both were about to have a
  second copy — the hospital upload sends the same multipart shape to the same endpoint as the
  patient locker, and needs the same local-timezone "today" for the same reason (deriving it
  from an ISO string uses UTC and, west of Greenwich in the evening, offers a "today" the API
  rejects as future-dated). The patient app re-exports both from its own `records/{api,view}`,
  so nothing else there moved. Behaviour-neutral and measured: patient bundle byte-identical in
  size (653,301 B), CSS hash unchanged, its 121 tests untouched.
- **Hospital portal — Slice 2, doctor management.** The roster (`GET /hospitals/me/doctors`)
  plus activate and deactivate, in `doctors/{api,view,useDoctors}` with dumb components — the
  only surface anywhere for ADR-015 step 3. Sectioned so whoever is waiting on the
  administrator comes first: pending, then active, then suspended. A status change does not
  refetch — the API answers with the updated row, that status is remembered, and grouping
  re-files the one card; every other card is left as it was, the same approach the patient
  portal takes when withdrawing a grant.
  **Both actions are labelled by what they truly do**, which took reading `consent.enforce`
  rather than guessing. Activation is permission to *ask*: an active doctor can search a Health
  ID and request access, and still reaches no record without the patient's consent for that
  category — so the card says it grants no record access. Suspension takes effect on the
  doctor's next request because `_acting_clinician` refuses a suspended clinician *even where a
  live grant survives*, and it withdraws no consent, so reactivating restores access without
  anyone consenting again. Both sentences sit beside the button rather than behind a
  confirmation dialog: the calls are idempotent and reversible, and text read before pressing
  beats text dismissed after. The status vocabulary is the doctor portal's own
  ("Active" / "Pending activation" / "Suspended"), so an administrator and a clinician never
  read two different words for one state. A 404 on either action is worded without claiming
  which of the two causes it was — the API conflates "unknown doctor" and "another hospital's
  doctor" deliberately. The empty roster shows the hospital's `HID-XXXX` (with a copy button)
  because a hospital cannot add a doctor — doctors register themselves against that ID — and an
  unverified hospital is told registrations are refused rather than handed an ID that will not
  work. Web tests 277 → 293. No backend, API, OpenAPI or generated-client changes.
- **Hospital portal — Slice 1, identity and registration.** `GET /hospitals/me` behind
  `profile/{api,view,useHospitalProfile}` and `POST /hospitals/register` behind
  `register/{api,view,useHospitalRegistration}`, in the layering the other portals use: the
  generated client is touched only by `api.ts`, every string the UI shows is worded in
  `view.ts`, and the components are dumb. 403 and 404 on `/hospitals/me` are read as
  *unregistered* rather than as failures, so a fresh account is routed to onboarding instead of
  an error screen — the pattern the doctor portal established. Screens: a dashboard and a My
  Hospital page (name, `HID-XXXX`, address, administrator, registration date, verification
  badge) plus an onboarding page outside the navigation shell.
  **The PENDING state is stated in terms of what it blocks** — doctors cannot register to the
  hospital and no records can be uploaded — because those are the two things ADR-015 actually
  refuses, and a badge that only said "Pending" would leave an administrator guessing why
  nothing works. Verification is reported, never offered: only a SYSTEM_ADMIN can grant it, so
  a button here would always 403. The registration form warns that it creates a *new* hospital;
  there is no endpoint that adds a second administrator to an existing one, so an unwarned
  administrator would silently end up with a duplicate organisation under a different HID.
  Also fixes a Slice 0 gap: `apps/hospital/tsconfig.json` had no `@/*` path mapping — Vite had
  the alias, TypeScript did not, and Slice 0 used no `@/` imports so nothing surfaced it.
  Web tests 255 → 277. No backend, API, OpenAPI or generated-client changes.
- **Hospital portal — Slice 0, the application shell.** The third portal is no longer an M0.1
  scaffold: Tailwind v4 + `@pulseos/ui/tokens.css` + the `@source` line the shared primitives
  need, `src/api.ts` (the single client instance), Google sign-in via the shared
  `AuthContextProvider`, `ProtectedRoute` around `HospitalLayout`, and a Sidebar/TopBar shell
  driven by one `navigation.ts`. Routes `/login`, `/`, `/hospital`, with `/dashboard`
  redirecting to `/` so one URL stays canonical. No new dependencies — everything resolved from
  the existing lockfile. The auth layer and every UI primitive come from `@pulseos/ui`; nothing
  was duplicated to make this portal work, which was the point of hoisting the kit first.
- **M4.3 `GET /api/v1/granted-records` (ADR-020)** — the step the consent flow was missing: a
  clinician holding a grant could not obtain a single `record_id`, because `GET /records` is
  patient/hospital-only, `/records/existence` returns no identifiers, `/consent-grants` is
  patient-only, and record ids are random. DOCTOR-only and ACTIVE-only; the page is *filtered*
  by the categories consent reports as granted and returns a chooser projection — id, category,
  origin, date of service, uploading hospital, created at — with `grantedCategories` beside it so
  "nothing was approved" is distinguishable from "what was approved is empty". Filename,
  description, size, content type and processing status are withheld and stay on the single
  authorized read. Hidden records never appear. **The listing permits nothing:** every record
  opened from it still crosses `consent.enforce` once, so an id survives revocation by exactly
  zero seconds. Audited as **one** event per request — `RECORDS_LISTED`, or `ACCESS_DENIED` when
  nothing is in scope — never one per row. Backend tests 328 → 368.
- **M4.2 Doctor portal — first vertical slice:** login → dashboard → patient search. The
  dashboard renders the clinician's own profile from `GET /doctors/me` (name, hospital,
  ACTIVE/PENDING/SUSPENDED badge, registration number) and a search card; `/patients` searches by
  Pulse Health ID against `GET /records/existence` and lists the available record categories —
  names only, no counts, filenames, hospitals or dates. A non-ACTIVE clinician sees their real
  status and a disabled search (ADR-015). Access requests are **not** part of this slice. 16 tests.
- **`@pulseos/ui` is now the shared portal foundation** (ADR-003: "share components, tokens", and
  do not triple auth plumbing). The auth layer (`provider`, `firebase`, `firebaseAuthProvider`,
  `devMockAuthProvider`, `AuthContext`), `ProtectedRoute`, `LoadingScreen`, `apiResult`,
  `useApiResource`, `cn`, `initialsFor` and **`tokens.css`** moved out of the patient app; both
  portals now compile the same palette, so the surfaces cannot drift. shadcn primitives stay
  per app deliberately — that is the shadcn model, and sharing them would drag the whole UI kit
  into the package. Behaviour-neutral: the patient app's 111 tests and its CSS hash are unchanged.
- **M4.1 `GET /api/v1/records/existence`** — the clinician-facing record-existence projection
  (SYSTEM_ARCHITECTURE §Consent Flow step 1). DOCTOR-only and ACTIVE-only; answers
  `{items:[{code, displayName}]}` for a Pulse Health ID and nothing else — no record ids,
  filenames, hospitals, dates, descriptions or counts. Hidden records are excluded. One grouped
  SQL query. It deliberately does not pass `consent.enforce`, which cannot answer a
  per-record question before any grant exists; the ADR-015 ACTIVE check is the relationship this
  module *can* decide, and every read past discovery still crosses the choke point once. Backend
  tests 300 → 320.
- **Patient-facing identity projection** — `records.directory.StaffDirectoryService` publishes
  display-safe staff facts (full name, specialty, hospital name; no identifiers, no employment
  status), consumed by consent through a `StaffDirectory` protocol. Batched by construction: a
  collection in, a mapping out, one statement per identity kind per page, with an N+1 guard test
  that counts SQL statements. Adds `requester` to the access-request listings, `grantee` to the
  grants listing and `actor` to audit entries, so patients read names instead of UUIDs.
- **`GET /api/v1/consent-grants`** — the patient's grant history (revoked and expired included),
  each row carrying a derived `status` (ACTIVE / REVOKED / EXPIRED) read with the same predicate
  enforcement applies, so the listing can never call a grant active that a read would refuse.
- **`GET /api/v1/audit-logs`** — the patient-facing append-only trail, keyset-paginated on the
  application-assigned `occurred_at`. Exposes the action, the actor and the role they held, the
  target (category by code), the event time and the tamper-evidence digest; deliberately omits
  `patientId`, `requestContext` and the storage timestamp.
- **M4 Patient portal integration:** all seven pages (Dashboard, Medical Records, Consent
  Requests, Active Grants, Audit History, Profile, Settings) rebuilt against the real API, each
  as `src/<feature>/{api,view,use*}` with dumb components and all mapping in `view.ts`. Records
  supports listing, detail, presigned download and locker upload; Consent supports per-category
  approve/reject without a refetch; Grants groups one approval's rows into one card and revokes
  them together; Audit renders the trail with a page-scoped summary that says so. Every mock
  module was deleted except `src/data/settings.ts`. Web tests → 131.

### Fixed
- **An unconfigured Firebase project reported itself as a client error.** `firebase_admin`
  signals a missing project id with a bare `ValueError` — the same type it raises for a
  malformed token — so `FirebaseAuthProvider` mapped it to `InvalidTokenError` and answered
  **401 "Invalid authentication token."**, blaming the caller for the server's own missing
  configuration, while `core/config.py` promised 503. `_get_app` now verifies the SDK resolved a
  project and raises `AuthProviderUnavailableError` → **503**, logging which variable to set.

- **M3 Consent Domain (backend):** the `consent` module — access request → per-category
  approve/reject → revoke, with `consent.enforce()` attached to every non-owner record read.
  Migration 0004 adds five tables: `consent_requests`, `consent_request_categories`,
  `consent_decisions` (immutable), `consent_grants` (what enforcement reads, O(1) by index),
  and the append-only `audit_logs`. Two invariants are enforced by the database rather than by
  code: a decision may only answer a category the request asked for (composite foreign key),
  and an approval spawns exactly one grant (unique `decision_id`). Six endpoints under
  `/api/v1/access-requests` and `/api/v1/consent-grants`. Every consent decision, revocation,
  allowed read and **denied** read appends an audit event in the same transaction as the action
  (`ACCESS_DENIED` added to the vocabulary, ADR-018), hashed for later on-chain anchoring
  (SHA-256 for now, ADR-019). `records` gained a published identity/vocabulary seam
  (`records/directory.py`) and a `ConsentEnforcer` port, making the records ⇄ consent dependency
  explicit and cycle-free (ADR-016); audited read failures return their RFC 7807 response rather
  than raising it, so a refusal is durably recorded (ADR-017). Patient-controlled visibility is
  honoured: a hidden record is invisible to a clinician holding a valid grant, and unchanged for
  its owner and its uploading hospital. Hospital-admin own-upload reads keep their M2 behaviour
  (ADR-013 layer 2). Backend tests 194 → 268; the ROADMAP M3 gate is walked over HTTP across two
  simulated hospitals. **Not included:** notifications fan-out, the `AuditAnchor` interface, the
  clinician-facing record-existence projection, a patient audit-log endpoint, and all M3
  frontend work.
- **M2 Backend Core (records module):** hospital + admin and doctor self-registration with
  System-Admin hospital verification and admin-managed doctor activation (ADR-015);
  `MedicalRecord` (FHIR DocumentReference-aligned) with migration 0003; multipart record
  upload → S3/MinIO behind an `ObjectStorage` port (hospital-for-Health-ID and patient
  locker flows); relationship-scoped metadata listing (cursor pagination, category filter)
  and short-lived presigned download URLs; arq chosen as the job queue (ADR-014) with a
  `JobQueue` port, worker entry point (`arq app.workers.main.WorkerSettings`) and a
  no-op `record_uploaded` task; seed extended with demo hospital staff and 3 synthetic
  patients (pinned valid Health IDs). Doctors deliberately have **no** record access until
  the consent module (M3). Backend tests 106 → 194.
- **M0.3 Walking Skeleton** (shipped in PR #1): auth module (Firebase port, role gates),
  patients module (registration, ADR-012 Health ID issuance, profile), migrations 0001–0002,
  DB/logging/RFC 7807 plumbing, OpenAPI-generated api-client, patient web login → profile,
  idempotent seed system.
- M0.2 Domain Foundation & Identity Design (docs-only): `docs/DOMAIN_MODEL.md` (entities,
  relationships, RBAC matrix, Health ID design, open decisions OD-1…3) and ADR-011 (Firebase
  Auth evaluation), ADR-012 (Health ID format), ADR-013 (RBAC layers).

### Changed
- Milestone renumbering after the M0 split: the walking skeleton is now **M0.3** (M0.2 became
  the domain design milestone). Stale M0.2 references in scaffold comments updated accordingly.

## [0.1.0] — 2026-07-20 · M0.1 Engineering Workspace & Project Scaffold

### Added
- Repository structure per approved architecture: `backend/`, `web/`, `mobile/`, `contracts/`, `infra/`, `scripts/`, `.github/`, `docs/`, `.claude/`.
- Backend skeleton: FastAPI app factory with `/health` liveness endpoint, env-driven Pydantic settings (`PULSEOS_` prefix), module packages for the six monolith modules (ADR-001), placeholder tests.
- Backend tooling: Ruff (lint + format, replaces Black — see docs/CONTRIBUTING.md), mypy strict with pydantic plugin, pytest (+coverage), all configured in `pyproject.toml`.
- Web monorepo: pnpm workspace with three Vite/React app shells (patient :5173, doctor :5174, hospital :5175) and shared packages `@pulseos/config` (tsconfig bases), `@pulseos/ui` (with vitest wiring), `@pulseos/api-client` (placeholder until OpenAPI generation lands).
- Web tooling: ESLint 9 flat config + typescript-eslint + react-hooks, Prettier, TypeScript strict.
- Local infrastructure: `infra/docker-compose.yml` — PostgreSQL 16 with pgvector (ADR-002), Redis 7, MinIO + one-shot bucket bootstrap; named volumes, dedicated network, healthchecks, safe local defaults.
- Root tooling: `.editorconfig`, `.env.example` (documented, milestone-annotated), `Makefile` (env/up/down/install/dev-*/lint/typecheck/test/ci), updated `.gitignore`.
- CI: GitHub Actions workflow — backend job (ruff format check, ruff lint, mypy, pytest) and web job (prettier check, eslint, tsc, vitest) with dependency caching.
- README rewritten as a self-sufficient developer quickstart.

### Notes
- No business logic, database schema, API endpoints (beyond `/health`), auth, frontend pages, AI, or blockchain code — by design; those begin at the walking skeleton (now M0.3) per `.claude/ROADMAP.md`.
- Alembic wiring deferred to the walking skeleton (now M0.3, first migration), since M0.1 forbids schema work.
