# Changelog

All notable changes to PulseOS are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: milestone-based pre-1.0.

## [Unreleased]

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
