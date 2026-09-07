# DECISIONS.md — Architecture Decision Records

> One entry per non-obvious decision. Status: Proposed → Accepted → (Superseded by ADR-NNN).
> New decisions get the next number. Never delete an ADR; supersede it.

---

## ADR-001 — Modular monolith instead of six microservices
**Date:** 2026-07-20 · **Status:** Accepted

**Context:** The original plan specifies six microservices (Auth, Patient, Record, Consent, AI,
Notification) behind an API gateway. The team is 3 students with near-zero ops experience; the
consent flow requires strong transactional consistency between consent grants, record access, and
audit logging.

**Decision:** One FastAPI application ("modular monolith") with six internal modules matching the
original service boundaries. Strict module isolation: modules communicate through service-layer
interfaces, never through each other's tables. Async work (OCR, embeddings, notifications) runs
in separate worker processes consuming a Redis queue — so the *deploy units* are: api, worker,
db, redis, object-store. FastAPI itself is the gateway (auth middleware, rate limiting, routing).

**Why:** Microservices would cost the team distributed tracing, inter-service auth, N pipelines,
network failure modes, and eventual-consistency bugs in the *consent path* — the one place
correctness matters most — while delivering zero benefit at this scale. The résumé/paper value is
preserved: the module boundaries ARE the service boundaries, and the paper can present the
architecture as "microservice-ready." Splitting later is a deploy change, not a rewrite.

**Consequences:** Single DB with per-module schema ownership conventions (DATABASE_DESIGN.md);
one codebase to test; the AI module's heavy dependencies live in the worker image, keeping the
API image slim.

---

## ADR-002 — pgvector instead of FAISS
**Date:** 2026-07-20 · **Status:** Accepted

**Context:** Plan specifies FAISS for RAG vector search. FAISS is an in-process index with no
persistence story, no metadata filtering, and no multi-tenancy — every worker restart means
rebuild, and per-patient scoping must be hand-rolled.

**Decision:** Use PostgreSQL + pgvector. Embeddings live in the same database as record metadata.

**Why:** RAG queries here are always scoped ("records of patient X that requester Y may see") —
that is a SQL `WHERE` clause + vector similarity, which pgvector does natively and FAISS does
not. One less system, durable by default, consent filtering happens in the same query as
retrieval (security property, not just convenience). Corpus size (thousands of chunks, not
millions) is far below where FAISS wins on performance.

**Consequences:** LangChain's pgvector integration is used; the paper describes "consent-scoped
retrieval" — a nice research detail. If scale ever demands it, swap behind the retriever interface.

---

## ADR-003 — Single React monorepo for all three web portals
**Date:** 2026-07-20 · **Status:** Accepted

**Context:** Plan implies three separate React apps (patient, doctor, hospital) built by one
frontend lead, plus a Flutter app.

**Decision:** One pnpm workspace: `web/apps/{patient,doctor,hospital}` + shared packages
`web/packages/{ui,api-client,config}`. The API client is generated from the backend's OpenAPI
spec (type-safe end to end). Vite + React + TypeScript strict + Tailwind.

**Why:** Three separate repos/apps triples dependency upkeep, design drift, and auth plumbing for
one person. Shared UI kit + shared typed client is the only way one frontend lead ships three
portals in the timeline.

**Consequences:** Apps stay separate at the routing/deploy level (a hospital admin never loads
patient code), but share components, tokens, and the client.

---

## ADR-004 — Hash-only on-chain consent anchoring behind a pluggable interface
**Date:** 2026-07-20 · **Status:** Accepted

**Context:** Plan says "consent recorded permanently on blockchain" (Polygon Amoy, Month 6),
while the consent service ships Month 3–4. Public chains must never hold PHI — even encrypted —
and testnets are unreliable and get deprecated.

**Decision:**
1. PostgreSQL (append-only audit table) is the **authoritative** consent/audit store and the only
   read path.
2. An `AuditAnchor` interface exists from Month 3 with a DB-backed implementation; Month 6 adds a
   `PolygonAuditAnchor` that writes `keccak256(canonical_event_json)` + event type + timestamp —
   **hashes only, never identifiers or PHI** on-chain.
3. Anchoring is asynchronous (queued) and non-blocking: chain downtime never delays or blocks a
   consent decision. A reconciliation job detects unanchored events and tampered rows.

**Why:** This is both the secure design (no PHI on a public chain; GDPR/DPDP "right to erasure"
stays satisfiable since only hashes are immutable) and the correct research framing:
*tamper-evidence*, not on-chain storage. It also de-risks the roadmap — blockchain becomes a
plug-in, not a Month-6 rewrite of the consent service.

**Consequences:** The paper's RC-2 experiment is exactly the reconciliation job: tamper a DB row,
show detection. Demo works even if Amoy is down.

---

## ADR-005 — S3-compatible object storage only; Cloudinary dropped
**Date:** 2026-07-20 · **Status:** Accepted

**Context:** Plan lists "AWS S3 / Cloudinary" ambiguously.

**Decision:** S3 API everywhere: MinIO in local docker-compose, real S3 (or Render-compatible
S3 service) in production. Access exclusively via short-lived presigned URLs issued **after** a
consent check. Server-side encryption on. No public buckets.

**Why:** One storage abstraction, identical code local vs prod. Cloudinary is a media-transform
CDN — wrong tool for confidential medical documents.

---

## ADR-006 — FHIR-aligned record metadata
**Date:** 2026-07-20 · **Status:** Accepted

**Context:** The plan defines an interoperability platform but never mentions HL7 FHIR — the
global (and India-ABDM) standard. Health-informatics reviewers will notice.

**Decision:** Model core metadata on FHIR resource shapes: `Patient`, `Practitioner`,
`Organization`, `DocumentReference` (records), `Consent`, `AuditEvent`. We do **not** run a FHIR
server or implement the full spec — we align field names/semantics and record category codes so
an export-to-FHIR mapping is trivial.

**Why:** Near-zero extra cost now; makes RC-4 credible; keeps the "future ABHA integration" claim
honest (ABDM is FHIR-based).

---

## ADR-007 — LLM provider abstraction; Gemini primary; PHI redaction before external calls
**Date:** 2026-07-20 · **Status:** Accepted (provider choice pending PO confirmation)

**Context:** Plan says "Gemini API / OpenAI" interchangeably. Medical text is sent to a third
party; providers differ in cost and API shape.

**Decision:** All LLM/embedding calls go through an internal `LLMProvider` interface. Default
provider: Gemini (free tier fits budget). Before any external call, a redaction step strips
direct identifiers (name, phone, Health ID, address) from prompt content; records are referenced
by opaque tokens. Prompts and redaction rules live in versioned code, not scattered strings.

**Consequences:** Provider swap is config; the redaction layer is a security control AND a
paper-worthy implementation detail.

---

## ADR-008 — Redis-backed async job queue for OCR, embeddings, notifications, anchoring
**Date:** 2026-07-20 · **Status:** Accepted

**Context:** OCR of a scanned PDF takes seconds-to-minutes; embeddings and LLM calls are slow;
the plan has no async story, which would mean request-thread OCR (timeouts, terrible UX).

**Decision:** Redis + a Python task queue (arq or Celery — pick at M2 start; arq preferred for
simplicity with asyncio). Upload returns immediately; processing status is tracked on the record
(`uploaded → processing → indexed | failed`) and surfaced in the UI.

---

## ADR-011 — Authentication provider: Firebase Auth (evaluated vs Keycloak, Authentik, custom JWT)
**Date:** 2026-07-20 · **Status:** Accepted (M0.2 evaluation)

**Context:** M0.2 required a formal comparison before implementation. Requirements: phone-OTP
login (primary flow for Indian patients), Google login, role claims for 4 roles, near-zero ops
for a 3-student team, and credibility for the paper/demo.

**Comparison (1–5, higher better):**

| Criterion | Firebase Auth | Keycloak | Authentik | Custom JWT |
|---|---|---|---|---|
| Security | 4 — Google-operated, battle-tested; vendor trust required | 5 — mature OIDC, self-hosted control | 4 — solid, younger ecosystem | 1 — hand-rolled crypto/session handling; highest risk |
| Scalability | 5 — managed, effectively unlimited at our scale | 3 — scales, but you run/tune it | 3 — same | 2 — everything is on us |
| Complexity (lower = better score) | 5 — SDK + token verify, no infra | 2 — Java server, realms, DB, upgrades; SMS OTP needs plugins + paid gateway | 2 — extra always-on service to host | 3 — simple to start, endless edge cases (refresh, rotation, revocation, OTP delivery) |
| Learning value | 3 — integration-level learning | 5 — real OIDC/IAM depth | 4 | 4 — but the lessons come as vulnerabilities |
| Suitability for PulseOS | 5 — phone OTP out of the box, free tier, FCM synergy | 2 — ops burden lands on the consent-flow timeline | 2 — same | 1 — building auth steals time from the actual research contribution |
| Resume value | 3 — ubiquitous | 5 — enterprise IAM keyword | 3 | 2 — "rolled own auth" is a red flag, not a credential |
| **Total** | **25** | **22** | **18** | **13** |

**Decision:** **Firebase Auth**, kept behind an internal auth port: the backend verifies ID
tokens and maps them to internal Users/roles in ONE dependency (`auth` module); custom claims
carry the role; nothing outside the auth module touches Firebase types. SMS-OTP costs are
controlled with Firebase test numbers in dev and Google-login fallback.

**Why not Keycloak despite the higher resume value:** its 5s are in dimensions we don't need
(enterprise federation, self-hosting) and its 2s are exactly where this project dies (ops load,
SMS OTP friction, time). The port design preserves the option to swap to Keycloak later as a
contained change — that architecture is itself the resume line.

---

## ADR-012 — Health ID format: random Crockford-Base32 with check character
**Date:** 2026-07-20 · **Status:** Accepted

**Decision:** `PHI-IND-YYYY-XXXXXXC` — 6 crypto-random Crockford-Base32 chars (≈1.07B/year
space) + ISO 7064 mod 37-2 check character. Generated by draw-and-insert against a unique
constraint; never reissued. Patient additionally carries a FHIR-style identifier list so ABHA
(or any external system) attaches later without remodeling; all internal FKs are UUIDs.
Identity QR encodes only the versioned ID URI (`pulseos://p/v1/<id>`) — no PHI, no signature;
the server is the authority and scan-driven search is authenticated, rate-limited, audited.

**Why (supersedes the master plan's sequential `000001` examples):** sequential IDs are
enumerable (probe which patients exist) and leak volume; randomness removes both at zero UX
cost. Check character gives offline typo detection at reception desks. Full design:
docs/DOMAIN_MODEL.md §4.

---

## ADR-013 — RBAC model: role gate + relationship check + consent check; SYSTEM_ADMIN added
**Date:** 2026-07-20 · **Status:** Accepted

**Decision:** Four roles (`PATIENT, DOCTOR, HOSPITAL_ADMIN, SYSTEM_ADMIN` — the last is new;
the master plan had no platform-operations role). Authorization is three ordered layers:
(1) static role gate per endpoint, (2) relationship conditions (own profile / own hospital /
own upload), (3) consent grants via the single `consent.enforce()` choke point. Permission
matrix: docs/DOMAIN_MODEL.md §3. Two invariants: System Admin can never read medical content
(no admin break-glass exists), and AI features inherit exactly the caller's consent scope.
Consent grants are per **individual doctor** and per **category** (not hospital-wide) in MVP.

---

## ADR-014 — Async job queue library: arq
**Date:** 2026-08-28 · **Status:** Accepted (the decision ADR-008 deferred to M2 start)

**Context:** ADR-008 mandates a Redis-backed task queue for OCR, embeddings, notifications, and
anchoring, with the library choice (arq vs Celery) deferred to M2 start. The backend is fully
async (SQLAlchemy async, FastAPI); the worker shares its codebase (ADR-001).

**Decision:** **arq.** Reasons: native asyncio (Celery's async story is bolted on — our worker
code would either block or juggle event loops), one small dependency instead of Celery's
kombu/billiard stack, typed (py.typed), and its feature set (retries with backoff, job
uniqueness, cron) covers everything the roadmap needs through M6. Celery's advantages
(multi-broker, rate-limited queues at scale) solve problems this project will never have.

**Consequences:** `app/core/queue.py` defines a `JobQueue` port (enqueue-only — the API never
consumes jobs) with `ArqJobQueue` and an in-memory fake; the worker entry point is
`arq app.workers.main.WorkerSettings`. Enqueue failures never fail the originating request:
the job is advisory at M2 (processing pipeline lands at M5), so the failure is logged
(IDs only, no PHI) and the record simply stays `UPLOADED`. M5 must add reconciliation for
missed jobs (e.g. a sweep for stale `UPLOADED` records) when processing becomes load-bearing.

---

## ADR-015 — Onboarding flows for hospitals, hospital admins, and doctors
**Date:** 2026-08-28 · **Status:** Accepted (M2; flagged for PO review — see SESSION.md 013)

**Context:** M2 requires "hospitals + doctor management with RBAC". DOMAIN_MODEL defines the
entities and the permission matrix (admin manages own hospital's doctors; admin registers own
hospital; System Admin verifies) but not the onboarding sequence. An "admin adds doctor"
flow would need either the doctor's Firebase identity in advance or an invite pipeline
(notifications module — not built). Claims can only be provisioned on an authenticated subject.

**Decision:** Self-registration + verification, mirroring the proven patient pattern:
1. **Hospital + admin:** an authenticated, unprovisioned user calls `POST /hospitals/register`
   → creates the Hospital (`PENDING`, random draw-and-insert `HID-XXXX`), the admin's User
   (`HOSPITAL_ADMIN`) + HospitalAdmin profile, and provisions claims — atomically, idempotently.
   A `PENDING` hospital cannot take doctor registrations or upload records.
2. **Verification:** `POST /hospitals/{hid}/verify`, SYSTEM_ADMIN only (RBAC matrix), idempotent.
   The three simulated hospitals are seeded `VERIFIED`.
3. **Doctor:** an authenticated, unprovisioned user calls `POST /doctors/register` naming a
   VERIFIED hospital's HID → User (`DOCTOR`) + Doctor profile in status `PENDING`; the hospital's
   admin activates/deactivates via `POST /hospitals/me/doctors/{id}/activate|deactivate`.
   A non-`ACTIVE` doctor will fail the relationship layer for every clinical capability (M3+).

**Why:** zero new infrastructure, single registration idiom across all roles, and the trust
gap ("anyone can claim to work at TMH") is closed by the two human verification steps
(System Admin verifies hospitals; hospital admins verify their doctors) instead of by an
invite system we'd have to build early. Invites can replace step 3 later without schema changes.

**Consequences:** Hospital IDs are random 4-digit draws (10k space is fine at 3–50 hospitals;
hospitals are public entities, so ADR-012's enumeration concern does not apply). Live demo
gap: attaching a *real* Firebase login as admin of a *seeded* hospital needs a small ops
script (set claims + insert profile row) — tracked in TODO, not solved by this ADR.

---

## ADR-016 — records ⇄ consent: a bidirectional dependency, each direction through one published file
**Date:** 2026-09-01 · **Status:** Accepted (M3)

**Context:** M3 needed two things to cross a module boundary in opposite directions. Consent
must resolve a caller to a practitioner, because ADR-013 makes the grantee an individual
doctor — and `Doctor` lives in `records` (a placement made at M2 for want of a better home,
and flagged then as the thing that would force this question). Records must ask consent
whether a read is permitted, because SYSTEM_ARCHITECTURE rule 3 puts every non-owner read
through one choke point. Isolation rule 1 forbids either module querying the other's tables.

**Decision:** Accept a bidirectional module dependency, constrained so that each direction
crosses exactly one file and neither crosses a table:

1. **consent → records** via `records/directory.py`, which publishes `ClinicianDirectoryService`
   and `RecordCategoryDirectoryService` returning records-owned projections (`ClinicianProfile`,
   `CategoryRef`), plus the session factories that build them. Consent adapts those projections
   into its own `Clinician` and `CategoryVocabulary` types.
2. **records → consent** via a one-method `ConsentEnforcer` protocol declared in
   `records/service.py`, plus consent's published `AuditAction` vocabulary and
   `AccessDeniedError`.

`records/directory.py` imports nothing outside `records`. That is the property preventing an
import cycle, and it is why the session factories live there rather than in
`records/dependencies.py` — a consumer must not have to know how another module assembles its
repositories.

**Why:** The alternatives cost more mid-milestone. Extracting an `organizations` module is the
right long-term answer but is a schema-and-boundary change with no Product-Owner ruling behind
it. Duplicating clinician identity inside consent would create two sources of truth for who a
practitioner is and whether they may act.

**Consequences:** The module graph is no longer a DAG, which is a real loss — the "microservice-
ready" claim of ADR-001 now has one edge that would need cutting first. Isolation rule 1 still
holds: no module queries another's tables, and both edges are typed, narrow, and greppable.
Extracting `organizations` later supersedes direction 1 of this ADR and leaves direction 2
untouched, because asking consent for permission is semantically correct wherever identity lives.

**Alternatives considered:** extract `organizations` now (correct, larger, unratified); duplicate
identity in consent (two sources of truth); have records implement consent's protocol directly
(makes records aware of its consumer, and would import consent types into `records/directory.py`,
closing the cycle this design avoids).

---

## ADR-017 — Audited read failures return their RFC 7807 response instead of raising it
**Date:** 2026-09-01 · **Status:** Accepted (M3, narrow — see Consequences)

**Context:** `get_db_session` owns one transaction per request and rolls back on any exception.
`consent.enforce` writes its `ACCESS_DENIED` audit row and then raises, which the record read
path converts into a 404. Raising an `HTTPException` propagates into FastAPI's dependency exit
stack, so the rollback discards the audit row that was the entire point of the call. The M3 gate
requires that attempted unauthorized reads be denied **and logged**; measured before the fix, a
denied read produced zero audit rows.

**Decision:** On the two record read endpoints (`GET /records/{id}`,
`POST /records/{id}/download-url`), build the problem response with the same `to_http_error`
mapping and **return** it rather than raising. The exit stack then unwinds without an exception
and the transaction commits, so the refusal is durable. The wire contract is unchanged: same
status, same `application/problem+json` body, same `X-Request-Id`.

**Why:** A read mutates nothing else, so the audit row *is* the whole transaction — committing on
refusal commits exactly the record of the refusal. Every other endpoint keeps raising, because a
failed write should roll back.

**Consequences:** Two endpoints now behave unlike the other twenty-one, which is a genuine
inconsistency and is the reason this ADR exists rather than a comment. More importantly, this
treats a symptom: **no security event survives a failed request anywhere else in the system.**
Hospital-admin denials (decided before the choke point) and any future audited 4xx have the same
hole. The durable fix is an audit sink that commits independently of the request transaction, or
an outbox; both change the "audit written in the same transaction as the action" rule in
DOMAIN_MODEL §1 and need their own ADR.

**Alternatives considered:** a separate audit session committing immediately (correct, changes a
documented invariant, deferred); commit-before-raise (not expressible with a dependency-scoped
transaction); accepting the loss (fails a stated gate criterion on the most sensitive path).

---

## ADR-018 — `ACCESS_DENIED` added to the audit action vocabulary
**Date:** 2026-09-01 · **Status:** Accepted (M3)

**Context:** DOMAIN_MODEL §1 lists nine audit actions, all of which record something that
happened; `RECORD_VIEWED` and `RECORD_DOWNLOADED` record successes. The M3 gate requires that
"attempted unauthorized reads are denied AND logged", and a refused read had no truthful action
to write.

**Decision:** Add `ACCESS_DENIED` to `AuditAction`. It is written by `consent.enforce` whenever
authorization fails, carrying the same actor, subject patient, category and record target as an
allowed read would.

**Why:** The alternative — recording a refusal as `RECORD_VIEWED` — falsifies a patient-visible,
tamper-evident log, which is the one artifact in this system that must not lie.

**Consequences:** Free at the schema level: enum columns are non-native `VARCHAR(32)` (revision
0001's rationale), so the vocabulary extended with no migration and no drift. DOMAIN_MODEL §1's
list is now a strict subset of the implemented vocabulary and should be amended to match.
`EMERGENCY_ACCESS` remains deliberately absent: break-glass is Phase 2 and needs its own ADR.

**Alternatives considered:** reuse `RECORD_VIEWED` (falsifies the trail); log denials only to
application logs (not patient-visible, not anchorable, not the authoritative store ADR-004
defines); no denial record at all (fails the gate).

---

## ADR-019 — SHA-256 event digests until keccak256 is available (M6)
**Date:** 2026-09-01 · **Status:** Accepted (M3, temporary — must be resolved before M6)

**Context:** ADR-004 specifies `keccak256(canonical_event_json)` because that is the digest a
Solidity contract verifies on-chain. Python's `hashlib` ships NIST SHA-3, which uses different
padding and is **not** keccak256, and the project has no keccak dependency.

**Decision:** `ConsentService` takes `event_hasher` as an injected callable. The default is
SHA-256. M6 supplies the keccak256 implementation through the same seam when the anchor lands.

**Why:** Adding an `eth-hash`/`pycryptodome` dependency at M3 buys nothing until there is a chain
to anchor to, and hashing nothing in the interim would leave the audit table with no tamper
evidence at all during M3–M5.

**Consequences — the constraint that matters:** `audit_logs` is append-only, so **a stored digest
can never be recomputed**. Switching the algorithm invalidates every row written before the
switch. Therefore the keccak hasher must be injected **before the first anchored audit row
exists**, i.e. as the first step of M6 and before any environment whose audit data is intended to
be verifiable. Until then, digests are internally consistent and detect tampering, but are not
on-chain-comparable. Tracked in TODO.md as an M6 prerequisite rather than an M6 task.

**Alternatives considered:** add the keccak dependency now (a dependency and a supply-chain
surface carried for three milestones before use); store both digests (doubles the column set for
a transitional period); defer hashing entirely (no tamper evidence during M3–M5, and ADR-004's
RC-2 experiment would have nothing to demonstrate against).

---

## ADR-020 — Clinician-scoped record listing: a dedicated resource, pre-filtered by grant scope
**Date:** 2026-09-04 · **Status:** Accepted (M4) · **Extends:** ADR-013, ADR-016, ADR-018

**Context:** The consent flow terminated at step 3. A clinician holding a valid, unrevoked,
unexpired grant could read a record **only if they already knew its UUID**, and no endpoint
would ever give them one: `GET /records` is gated to PATIENT and HOSPITAL_ADMIN (and its
service fails closed for every other role), `GET /records/existence` returns category presence
with no identifiers, `GET /consent-grants` is patient-only by design, and record ids are random
(ADR-012's no-enumeration rule). `GET /records/{id}` and the download URL admitted DOCTOR and
passed `consent.enforce`, but had no reachable input. The consent journey could be demonstrated
up to approval and no further.

**Decision:** a new resource, `GET /api/v1/granted-records?patientHealthId=&cursor=&limit=`,
owned by the `records` module, DOCTOR-only, requiring an ACTIVE clinician (ADR-015). Four parts:

1. **Authorization is a filter, not a verdict.** The page is narrowed to the categories consent
   reports as granted. `consent.enforce` is **not** called per record; every record opened from
   the page still crosses it exactly once, so an id learned here is refused the moment its grant
   is revoked.
2. **Three seams, not one.** `records/service.py` now declares `GrantScope`
   (`granted_category_ids`) and `ListingAuditor` (`record_listing`) beside the existing
   `ConsentEnforcer`, all implemented by `ConsentService` and wired to the same instance.
   `records` never restates a consent predicate and never touches `consent_grants`.
3. **A dedicated response schema.** `GrantedRecordResponse` exposes id, category code and
   display name, origin, date of service, uploading hospital and creation time — enough to
   *choose* a record. Filename, description, size, content type and processing status are
   withheld and remain available on the single authorized read. `grantedCategories` reports the
   scope beside the page.
4. **One audit event per request** — `RECORDS_LISTED`, or `ACCESS_DENIED` when nothing is in
   scope, written before the empty page is returned.

**Why not the alternatives:**

- *Reuse `GET /records` with role-aware behaviour* (smallest diff): one route would carry three
  different authorization bases, `patientHealthId` would be load-bearing for one role and
  ignored by two, and the response type would either fork by role — breaking a generated client
  — or be shared, so every field added later for patients silently reaches clinicians. It would
  also inherit finding M3-B: `GET /records` writes no audit event at all.
- *`GET /consent-grants/{grantId}/records`*: conceptually purest, but inverts ADR-016 direction 2
  (consent would serve records-owned data), requires a grantee-visible grant listing that does
  not exist, and turns one patient into N listings with N cursors for the client to merge.
- *Deepen `/records/existence` when a grant exists*: an endpoint whose disclosure level depends
  on data cannot be reviewed by reading it, and it would make a deliberately unaudited step
  sometimes-audited. Disclosure level must be a property of the route, not of the data.
- *Call `enforce` per record*: it writes an audit row per call and raises rather than returning a
  boolean, so filtering a page with it would record a `RECORD_VIEWED` for every record merely
  listed and an `ACCESS_DENIED` for every one filtered out — a trail of reads that never
  happened — at 2N + N queries.

**Consequences:**

- `AuditAction` gains `RECORDS_LISTED` (values in a `VARCHAR(32)` column, so no migration —
  ADR-018 precedent). Clients with an exhaustive action map must add an entry.
- **The `audit_logs` target-column rule relaxes from "exactly one" to "at most one."** A listing
  is an event about a *scope*: it spans every granted category and every record inside them, so
  no single target column can be filled truthfully, and filling one per row would multiply one
  action into a page-sized burst. Such an event sets none; `patient_id`, never nullable, carries
  its subject. "Never more than one" still holds without exception.
- SYSTEM_ARCHITECTURE rule 3 is now satisfiable in its precise form for clinicians: *every
  non-owner read of metadata-beyond-existence is audited*. Finding M3-B (owner and
  hospital-admin listings, still unaudited) is untouched and remains open on its own merits.
- `utc_now` moved to `app/shared/time.py`: a third module needed it, which is the condition
  `records/dependencies.py` already set for promoting a helper out of a module.
- The module graph keeps the one cycle ADR-016 accepted; this widens that edge from one seam to
  three, each one method wide and each answering a different question.
- **Not addressed:** rate limiting. `/granted-records` requires a live grant, so it is not a
  Health-ID oracle the way `/access-requests` and `/records/existence` are (finding M3-D), but
  the bucket those two need should cover it too.

---

## ADR-021 — Hospital patient lookup: a `patients`-owned identity endpoint, role-gated only

**Date:** 2026-09-07 · **Status:** Accepted (M4) · **Extends:** ADR-012, ADR-013, ADR-015

**Context:** `POST /records` files a document against a Health ID, and no endpoint edits or
deletes a record afterwards. A hospital administrator had no way to check whose history they
were about to write to: `GET /records/existence` is DOCTOR-only and returns no name, and
nothing else resolves a Health ID. A valid Health ID belonging to the wrong patient was
therefore an unrecoverable mistake, made at a reception desk, on the most sensitive write the
system has. The RBAC matrix already grants this capability — docs/DOMAIN_MODEL.md §3, "Search
patient by Health ID / QR: Hospital Admin ⭕ existence + name confirmation only" — it had
simply never been built.

**Decision:** `GET /api/v1/patients/lookup?healthId=`, owned by the `patients` module,
HOSPITAL_ADMIN-only, answering `{healthId, fullName}` and nothing else. Four parts:

1. **`patients` owns it, not `records`.** The disclosure is patient identity, and ownership
   follows the data (the rule `/records/existence` already applies in reverse: it lives in
   `records` because records owns category presence). No new table, no new repository
   method — `PatientRepository.get_by_health_id` already existed for the directory.
2. **Validated before it is queried.** The service runs `is_valid_health_id` first, so a
   mistyped ID is refused as malformed rather than as "no such patient". That is ADR-012's
   check character doing exactly the job it was specified for, and the two answers are
   different instructions to the person at the desk.
3. **Role gate only — no relationship layer.** Deliberately: every relationship an admin has
   (their HospitalAdmin row, their hospital's verification status) lives in `records`, so
   checking one would create a `patients → records` edge purely to gate a read that discloses
   nothing about records. The `HOSPITAL_ADMIN` claim can only exist because
   `POST /hospitals/register` created that profile, so the gate already implies a registered
   administrator. A PENDING hospital can therefore look a patient up but still cannot upload
   — the 409 stays where it was, and the lookup tells it nothing it could not learn by
   attempting the upload.
4. **A response allow-list, pinned by contract tests.** Two fields. Date of birth, gender,
   contact details, `created_at`, the internal UUID and everything medical are absent;
   widening it has to be a deliberate edit to `PatientLookupResponse`.

**Why not the alternatives:**

- *Widen `/records/existence` to HOSPITAL_ADMIN*: its contract is category presence with no
  identity, and the thing needed here is a name. One route would carry two disclosure levels
  chosen by role — the exact property ADR-020 rejected, because a route's disclosure must be
  reviewable by reading the route.
- *Own it in `records`, beside the upload it guards*: puts a patient-identity projection in a
  module that does not own patient identity, and duplicates the resolution the `patients`
  directory already publishes.
- *Return the patient id so the upload could take it instead of a Health ID*: would change
  the `POST /records` contract, put an internal UUID on the wire against DOMAIN_MODEL rule 4,
  and make the lookup load-bearing for authorization rather than for confirmation.

**Consequences:**

- **This confirms an identity; it authorizes nothing.** The upload re-resolves the Health ID
  and still requires a VERIFIED hospital. A UI that skipped the lookup would be no more
  permitted than before — which is what keeps this a safety feature rather than a new
  authorization path.
- **It is a Health-ID oracle that returns a name, and the first endpoint to do so.** It joins
  `POST /access-requests` and `GET /records/existence` in finding M3-D's rate-limiting bucket,
  and is narrower than both (HOSPITAL_ADMIN only; a malformed ID is refused before the
  database is touched). Rate limiting is not built here and remains M3-D's job.
- **Not audited**, for the same reason discovery is not: no record was accessed and no
  truthful `AuditAction` member exists. This widens that open question rather than settling
  it — a lookup discloses a *name*, which is a stronger disclosure than category presence, so
  whichever way the PO rules for `/records/existence` should now cover this too (TODO §1).
- The `patients` module gains its first non-patient caller. Its dependency direction is
  unchanged: it still imports only `auth`, and nothing imports it except through the
  directory.

---

## ADR-022 — Audit emission policy: what a hospital records, and what the schema cannot record

**Date:** 2026-09-07 · **Status:** Accepted (M4) · **Resolves:** findings M3-B, M3-E ·
**Extends:** ADR-016, ADR-018, ADR-020

**Context:** Before building a hospital-scoped audit view it was necessary to know what a
hospital actually emits. The answer was **nothing**: every hospital-admin path bypassed the
audit write. `_authorize_read` returns at ADR-013 layer 2 *before* `consent.enforce`, so
neither allowed nor refused hospital reads were recorded (M3-E); `GET /records` writes no
event (M3-B); `RECORD_UPLOADED` had been in DOMAIN_MODEL §1's vocabulary since M0.2 and in
`AuditAction` since M3 and was **written by nothing**. A view built first would have
rendered an empty page indefinitely.

**Decision — the emission matrix.** Two constraints decide most of it. `audit_logs` has no
hospital column, and `patient_id` is **NOT NULL**: every event must name a patient subject.

| Action | Ruling | Vocabulary | In 6a |
|---|---|---|---|
| Record upload (hospital + locker) | **Audit** | `RECORD_UPLOADED` | ✅ |
| Hospital own-upload read | **Audit** | `RECORD_VIEWED` | ✅ |
| Hospital download | **Audit** | `RECORD_DOWNLOADED` | ✅ |
| Hospital read denial | **Audit** | `ACCESS_DENIED` | ✅ |
| Owner (patient) listing | **Do not audit** | — | ✅ (ruling only) |
| Hospital listing | Audit, but not yet representable | `RECORDS_LISTED` | ⛔ 6b |
| Patient Health-ID lookup | Deferred | none exists | ⛔ |
| Doctor activate / deactivate | **Out of scope** | none | ⛔ |
| Hospital registration | **Out of scope** | none | ⛔ |

**M3-B — rule 3 means *non-owner*.** A patient listing their own records is the subject
reading their own index: it discloses nothing to anyone else, and logging it would grow the
trail without bound while saying nothing about *access* — the same argument
`list_audit_events` already makes for not auditing reads of the trail itself.
SYSTEM_ARCHITECTURE rule 3 is therefore read as covering non-owner reads, which ADR-020
already satisfied for clinicians. The hospital half is a genuine non-owner read and **should**
be audited — but a hospital's listing spans many patients, and `patient_id` is singular and
NOT NULL, so no single truthful row can express it and ADR-020 already refused the
one-row-per-record alternative. It waits for 6b.

**M3-E — hospital read outcomes are audited, on ADR-018's terms.** The *decision* stays in
`records` (only it knows who uploaded what); what changed is that both outcomes now reach the
trail. The previous asymmetry — a clinician's refused read visible to the patient, a
hospital's not — was indefensible for the party the log exists to serve. A read of a record
that does not exist still writes nothing: there is no patient to attribute it to and no data
was reached.

**Patient lookup — deferred, for a reason stronger than "not yet".** It has no truthful
vocabulary member, and adding one is ADR-sized (ADR-018/020 are the precedents). More
decisively: `patient_id` NOT NULL means only *successful* lookups are recordable, so the
audit would systematically miss the behaviour it would exist to catch — an actor probing
Health IDs that resolve to nobody. A half-blind identity-disclosure log is worse than an
acknowledged gap, because it reads as coverage. Revisit with 6b, alongside
`/records/existence` (TODO §1), where nullable-subject events can be considered properly.

**Doctor management and hospital registration — outside this log entirely.** DOMAIN_MODEL §1
defines AuditEvent as *patient-visible* with a patient subject. Activating a doctor or
registering a hospital involves no patient and could not be written without making
`patient_id` nullable, which would change what the table means. These are administrative
events and belong to a separate admin-activity log if one is ever wanted — not to a
patient's trail.

**The seam.** `records` gains a fourth protocol, `RecordAuditor`, beside `ConsentEnforcer`,
`GrantScope` and `ListingAuditor`, implemented by the same `ConsentService`. Two
purpose-named methods — `record_upload` and `record_direct_read` — rather than one general
"write an event", so `records` cannot reach the rest of the vocabulary: it may record an
upload and a relationship-authorized read, and there is no third thing it can say. Unlike
`enforce`, these ask nothing; `records` has already decided and the outcome arrives as a
parameter.

**Consequences:**

- The patient's trail is materially more complete: uploads and hospital reads were both
  invisible to the person the log is for.
- Upload auditing covers the **patient locker** too. `RECORD_UPLOADED` is unqualified in
  DOMAIN_MODEL §1, and a trail recording only hospital uploads would lie by omission about
  the patient's own.
- The audit write sits inside the upload transaction, after the object store succeeds, so a
  failed upload leaves no event and a later failure takes the event with it.
- **No schema change, no migration, no index, no `event_hash` change** — every event added
  fits the existing columns.
- 6b still needs `actor_hospital_id` recorded at write time (never a join through the
  actor's *current* hospital, which would move history when staff transfer) plus the actor
  index the `audit_logs` schema comment already anticipates.

---

## ADR-023 — Historical hospital attribution, and a versioned audit-hash scheme

**Date:** 2026-09-07 · **Status:** Accepted (M4) · **Extends:** ADR-004, ADR-016, ADR-019,
ADR-020, ADR-022

**Context:** ADR-022 gave hospitals audit *events*; they had no way to read them. `audit_logs`
carries no hospital, and the only alternative — joining `actor_user_id` to the actor's
**current** affiliation — would move history whenever staff transfer: events a doctor
generated at hospital A would migrate into hospital B's view the day they changed jobs. The
project had already ruled on this exact problem once, on `consent_requests.requester_hospital_id`
("Provenance, not a lookup: the hospital the requester acted for at request time").

**Decision:**

1. **`actor_hospital_id`, nullable, captured at write time.** UUID with a foreign key to
   `hospitals.id`. Nullable is a domain fact, not laziness: patients generate a large share
   of events — every consent decision, revocation, own read and locker upload — and belong to
   no hospital. It arrives at `_write_audit` as an argument, never a lookup, which is what
   makes "never reconstructed later" structural rather than a convention.

2. **`hash_version` selects the whole scheme — canonicalization *and* algorithm.** Not two
   orthogonal columns. v1 is revision 0004's ten-key payload under SHA-256; v2 adds
   `actor_hospital_id`; **v3 is reserved for ADR-019's keccak transition**, which now has a
   mechanism to land in instead of invalidating the table.
   **v1 omits the key entirely rather than emitting it as null** — that is precisely why
   legacy digests still reproduce. `canonical_event_payload` serves writing and verifying
   alike, so a verifier can never drift from the writer.
   `hash_version` is deliberately **outside** the hashed payload, and that is safe because
   any mis-selection is self-detecting: recomputing a v2 row under v1 drops a key the digest
   covered, and a v1 row under v2 adds one it did not. Both directions are tested.

3. **Legacy rows keep NULL and their digests.** No backfill: the only available source is the
   forbidden join. Hospital-scoped queries therefore begin at migration 0005 — a documented
   blind spot rather than a reconstructed fiction.

4. **Index `(actor_hospital_id, occurred_at, id)`**, the same shape as the patient index,
   which is unchanged. Rows with no hospital are absent from it by construction.

5. **`GET /api/v1/hospitals/me/audit-logs`** — HOSPITAL_ADMIN only, scope derived server-side
   from the admin profile, **no hospital parameter exists**. Owned by `consent` because
   ownership of the data decides the module and the URL only decides the shape (ADR-020's
   rule); it needs one fact from `records`, published as
   `StaffDirectoryService.administered_hospital_id`. Its response is a separate allow-list
   from the patient's — **no `patientId`** (a hospital reads its own activity, not a roster of
   the people it touched), no digest or `hashVersion` (tamper evidence is published to the
   *subject* of a trail, which a hospital is not), and nothing clinical.

**Deferred, with reasons recorded so 6c need not rediscover them:**

- **Hospital record *listing*** stays unaudited. Not because a hospital only sees its own
  uploads, but for a structural reason: one listing spans many patients while `patient_id` is
  singular and NOT NULL, so no single row can state it truthfully, and ADR-020 already
  refused the page-sized burst. It belongs to a future organisation-scoped operational log.
- **Patient lookup and `/records/existence`** stay unaudited. NOT NULL `patient_id` means only
  *successful* probes are recordable, so the log would systematically miss the enumeration it
  would exist to catch. Same future log.

**Consequences:** the patient-visible log keeps its meaning — `patient_id` was not relaxed —
while gaining a second truthful scope over the same rows. Three deferred items now point at
one missing artifact (an organisation/actor-scoped operational log), which should be designed
once rather than three times. 6c is unblocked for the UI only.

---

## ADR-009 — (placeholder) Deployment target: Render vs AWS
**Status:** Proposed — decide at M1 gate. Recommendation: Render (managed Postgres + Redis,
simplest path for students); AWS only if the team wants the learning curve.

## ADR-010 — (placeholder) Flutter app timing
**Status:** Proposed — decide at M1 gate. Recommendation: start Flutter in Month 4 *after* the
patient web portal stabilizes, reusing the proven API; web portal is the demo-critical patient
surface. Original plan had all four clients in Month 3, which overloads the single frontend lead.
