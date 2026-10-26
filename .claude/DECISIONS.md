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
**Date:** 2026-07-20 · **Status:** Accepted — **amended by ADR-029 (2026-10-11):** pgvector and
LangChain are not used by the current implementation; retrieval is deterministic and lexical, and
pgvector is deferred. The decision text below is preserved as recorded.

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
**Date:** 2026-07-20 · **Status:** Accepted — decision 2 amended by ADR-027 (2026-10-11)

**Context:** Plan says "consent recorded permanently on blockchain" (Polygon Amoy, Month 6),
while the consent service ships Month 3–4. Public chains must never hold PHI — even encrypted —
and testnets are unreliable and get deprecated.

**Decision:**
1. PostgreSQL (append-only audit table) is the **authoritative** consent/audit store and the only
   read path.
2. An `AuditAnchor` interface exists from Month 3 with a DB-backed implementation; Month 6 adds a
   `PolygonAuditAnchor` that writes `keccak256(canonical_event_json)` + event type + timestamp —
   **hashes only, never identifiers or PHI** on-chain.
   **Amended by ADR-027 (2026-10-11):** the per-event on-chain payload is replaced by one opaque
   32-byte commitment per Merkle batch of verified v3 events; no event type, event UUID or
   per-event digest goes on-chain. The interface and "hashes only" principle stand.
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
**Date:** 2026-07-20 · **Status:** Accepted (provider choice pending PO confirmation) —
**superseded in part by ADR-028 (2026-10-11):** the provider choice (Gemini) and the redaction
requirement are replaced; the provider-abstraction principle stands, implemented as the
`AnswerGenerator` protocol. The decision text below is preserved as recorded.

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
**Date:** 2026-07-20 · **Status:** Accepted — library chosen by ADR-014 (arq). **Note
(2026-10-11):** only the queue and a logging `record_uploaded` task exist; OCR, embedding,
notification and anchoring jobs are not implemented (see ADR-027, ADR-029). **Note
(2026-10-14):** notifications no longer belong to this queue — ADR-031 replaced that part with
in-app notifications written in the consent transaction (implemented, `15b2d1b`).

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

**Implementation Addendum (2026-10-17 — commits `b045f10`, `98f3b33`, `e48017a`, `96a2191`):**
- **System Admin Provisioning:** A local CLI script `scripts/dev_provision_system_admin.py` stamps
  Firebase custom claims `{"role": "SYSTEM_ADMIN", "system_admin": True}` on specified Firebase UID or email.
- **Hospital Directory Endpoint:** `GET /api/v1/hospitals` (requires `Role.SYSTEM_ADMIN`) lists all hospitals
  in the platform (both PENDING and VERIFIED), unblocking administrative verification.
- **Dedicated Admin UI:** The hospital portal frontend now provides an `AdminLayout` and dedicated dashboard
  (`web/apps/hospital/src/pages/AdminDashboardPage.tsx`) with platform-level metrics and verification controls.
- **Known Remaining Gaps:** `POST /api/v1/hospitals/{hid}/verify` sets `is_verified=True` but does not yet
  record the verifier's user ID or timestamp on the hospital row, nor emit an administrative audit event.
  Rejection/suspension lifecycle is not implemented.

**Note (2026-10-25 — commit `15e0b1c`):** the verifier gap above is partly closed. Migration
`0009` adds nullable `hospitals.verified_by_user_id` (FK → `users`) and `hospitals.verified_at`,
set only on the PENDING → VERIFIED transition in `verify_hospital`; hospitals verified before
0009 keep NULL. Still open: no administrative audit event (`audit_logs.patient_id` is NOT NULL),
no rejection lifecycle (`HospitalVerificationStatus` is only PENDING | VERIFIED). Separately,
`65b68fe` enforces `users.status == ACTIVE` and token revocation on every request; there is no
API to suspend a user or revoke tokens (out-of-band only).

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

**Amendment (2026-10-15 — implemented and committed in `a09d41f`; validated locally
on SQLite and PostgreSQL 16.15; formal Product Owner acceptance not recorded):** a third use of the same technique, on a write path.
`POST /access-requests/{id}/approve` and `/reject` now **return** the 409 for a request that is
no longer decidable instead of raising it (`consent/router.py::_decide`). Cause: expiry is
persisted lazily — the service sets `status = EXPIRED` when a decision arrives after the deadline
and then refuses — and raising rolled that transition back, so an expired request stayed stored
as PENDING indefinitely. Why it is safe here: the refusal (`RequestNotDecidableError`) is raised
by `_require_own_open_request` before any decision, grant, audit row or notification is written,
so the only pending state is the request's own PENDING → EXPIRED transition; committing commits
exactly that. Every other decision failure (duplicate answer, unrequested category, duplicate
grant) still raises and rolls back the whole decision. No service or repository commits; the
request-scoped transaction still owns the commit. Wire contract unchanged (409, same
problem+json body, `X-Request-Id`). Expiry stays lazy — there is no sweep — so listings derive
the status instead: a PENDING row past its deadline is reported as EXPIRED (`request_status`)
without writing during the read. Tests: `test_an_expired_request_is_shown_as_expired_and_the_
transition_is_persisted`, `test_other_decision_failures_still_roll_the_whole_decision_back`
(`tests/test_consent_http.py`).

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
**Date:** 2026-09-01 · **Status:** Accepted (M3, temporary) — **resolved at M6.1 (2026-10-11)**, see
Resolution below

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

**Resolution (M6.1, 2026-10-11):** keccak256 landed as **`hash_version` 3**, in the slot ADR-023
decision 2 reserved for it. v3 hashes v2's canonical payload byte for byte with Ethereum
Keccak-256 (`pycryptodome`'s `Crypto.Hash.keccak`; `hashlib.sha3_256` is the NIST variant and is
not used). New events are written under v3; v1 and v2 rows keep their SHA-256 digests and verify
under them — nothing is rehashed or relabelled. Because `hash_version` already selects the whole
scheme (ADR-023), the algorithm is now resolved from the row's version through one table in
`consent/service.py` (`event_hasher_for`) rather than injected: the `event_hasher` constructor seam
described above was removed, since a single injected function could hash a row under an algorithm
other than the one its version names. An unknown version is refused (`UnsupportedHashSchemeError`)
and verifies as `EVENT_ALTERED`, never as a default scheme. **Compatibility boundary:** only v3
digests are on-chain-comparable; v1/v2 rows remain verifiable locally only. Only verified v3
digests may enter on-chain anchoring, which per ADR-027 publishes one commitment per Merkle batch
of v3 digests rather than the digests themselves; admitting anything else requires a separately
designed and approved migration strategy.

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

**Amendment 1 (2026-10-15 — implemented and committed in `a09d41f`; formal Product
Owner acceptance not recorded): the clinician AI search reuses this listing's audit events.**
*(Its action was refined by Amendment 2 below; kept as written.)* `GET /ai/patients/{patient_id}/search` returned
ranked chunk text inside the clinician's granted scope with no audit row and no rate limit. It
now writes exactly one scope-level event per request through the same writer
(`ConsentService.record_listing`): `RECORDS_LISTED` when a scope was searched (written after
retrieval succeeds, also when nothing matched), `ACCESS_DENIED` when the scope was empty, and
nothing when the patient id names no patient (an audit row must reference a patient). The query
text and chunk content are never written to the row or logged. It has its own bucket,
`ai_search` (30 / 60 s), independent of `ai_generate`. The endpoint was kept rather than removed
because no `/api/v2` exists (API_GUIDELINES) and removing it would break v1; no portal calls it.
**Known limitation:** the trail cannot tell an AI search from an ordinary granted-records
listing — both are `RECORDS_LISTED` with no target column, and `request_context` is only a
correlation id — so the patient's "Records listed" understates a search that returned record
text. A dedicated action (e.g. `RECORDS_SEARCHED`) needs no migration (`VARCHAR(32)`, no CHECK)
but does need its own ADR, the backend enum member, OpenAPI/client regeneration and an entry in
the exhaustive action maps of the patient and hospital audit views; not done. Also open: the
query travels in the URL query string (the application's access log omits query strings;
proxies may not).
On the "Not addressed" note above: `/granted-records` has had its own `granted_records` bucket
since ADR-024.

**Amendment 2 (2026-10-15, same day — implemented and committed in `a09d41f`;
validated locally on SQLite and PostgreSQL 16.15; formal Product Owner acceptance
not recorded): the AI search gets its own action, `RECORDS_SEARCHED`.** This resolves the
"known limitation" of Amendment 1. Decision:

- `AuditAction.RECORDS_SEARCHED` — same shape as `RECORDS_LISTED`: one scope-level row per
  request, no target column, `patient_id` carries the subject. Written by
  `ConsentService.record_search`, which shares one private helper with `record_listing`; an
  empty scope is still `ACCESS_DENIED`, and an id naming no patient still writes nothing.
- **No migration.** Verified, not assumed: on the schema the migrations build (PostgreSQL,
  `alembic upgrade head`), `audit_logs.action` is `character varying(32)` with no CHECK
  constraint, and the ORM enum is `native_enum=False`
  (`test_the_migrated_audit_action_column_takes_records_searched_without_a_migration`). The
  value is 16 characters.
- **Backward compatible.** Rows written before this keep `RECORDS_LISTED`; nothing is
  rewritten (the table is append-only, and the action is part of the hashed payload). The
  ADR-018/ADR-020 precedent for extending the vocabulary applies unchanged.
- **Clients:** the OpenAPI spec and generated client were regenerated with
  `scripts/generate-api-client.sh`; the patient and hospital audit views map the new action
  ("Records searched (AI)"). Both views already render unknown actions safely (a humanized
  label in the patient view, "Audit event" in the hospital view), so an older build shows the
  row rather than dropping it.
- Still open: the query is sent in the URL query string (GET).

**Implementation Addendum (2026-10-17 — commit `d09d721`): Keyset pagination stabilization.**
Medical record keyset pagination (`GET /api/v1/records` and `GET /api/v1/granted-records`) was stabilized
with a deterministic composite order: `(date_of_service, created_at, id)` with `id` as tie-breaker. Keyset
filtering applies row-value comparison across `(date_of_service, created_at, id)` for both `NEWEST_FIRST`
and `OLDEST_FIRST` directions, preventing skipping or duplicating records across page boundaries when
timestamps collide.

---

## ADR-021 — Hospital patient lookup: a `patients`-owned identity endpoint, role-gated only

**Date:** 2026-09-07 · **Status:** Accepted (M4) — **amended 2026-10-15**: decision 3 (role gate
only) is superseded by a VERIFIED-hospital requirement; see *Amendment* at the end. The original
text is kept as written. · **Extends:** ADR-012, ADR-013, ADR-015

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

**Amendment (2026-10-15 — implemented and committed in `a09d41f`; validated locally;
formal Product Owner acceptance not recorded): verified hospitals only.** Decision 3's rationale does not hold. It said a PENDING hospital's lookup
"tells it nothing it could not learn by attempting the upload" — but the upload refuses an
unverified hospital (409) *before* resolving the Health ID and never returns a name. Because
`POST /hospitals/register` grants HOSPITAL_ADMIN immediately, any new account could therefore
turn Health IDs into names. Change:

- `GET /patients/lookup` now requires the caller to administer a VERIFIED hospital; otherwise
  **409** "Your hospital is not verified yet, so it cannot look patients up." — the status every
  other unverified-hospital refusal uses (upload, doctor registration).
- The check runs after the role gate and the rate limit (an unverified caller still spends
  `patient_lookup` quota) and **before** the Health ID is parsed or resolved, so issued,
  unissued and malformed IDs all receive the identical refusal.
- The rule stays in `records`, which owns hospitals: a read-only seam,
  `records.directory.HospitalVerificationDirectoryService.administers_verified_hospital`,
  composed in `patients/dependencies.py`. This adds the `patients → records` edge decision 3
  avoided — through the published directory only, the same pattern `consent` already uses. The
  `patients` service still performs no authorization (route-level gate).
- Unchanged: the two-field response allow-list, the 422 distinction between malformed and
  unknown Health IDs, and that the lookup authorizes nothing. Still **not audited** (no truthful
  `AuditAction`; the operational-log question in TODO.md stands).
- Tests: `tests/test_patient_lookup_http.py` (PENDING refused, identical answer for any ID,
  succeeds once verified, quota still spent); the fixture now verifies its hospital through the
  real SYSTEM_ADMIN endpoint.

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
   **Qualified (2026-10-11, M6.3):** "self-detecting" holds only when the stored digest is left
   unchanged *and* something recomputes the row. A relabel alone (e.g. a v3 row set to v2 with its
   Keccak digest untouched) no longer recomputes and is reported once checked — reconciliation
   now recomputes every unbatched event under its own version (ADR-027 decision 13) and per-event
   anchoring refuses such rows. A relabel **combined with a consistent digest rewrite** under the
   new version is, on current database evidence, indistinguishable from a genuine event of that
   version: nothing in the row records which version it was written under. Only sealing (and, once
   commitments are on-chain, the chain) or database-level append-only enforcement — deferred to
   M7 hardening — closes that window.

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

## ADR-024 — Rate limiting: a per-route dependency, fixed windows over Redis, fail-open

**Date:** 2026-09-07 · **Status:** Accepted (M3-D) · **Extends:** ADR-013, ADR-014 ·
**Amends:** docs/API_GUIDELINES.md §AuthN/AuthZ

**Context:** Three endpoints answered whether a Pulse Health ID exists, unthrottled, and one
of them returns the patient's **name** (ADR-021). ADR-012 chose random Health IDs precisely
to defeat enumeration; without a limiter that defence was half-built. Finding M3-D had been
open since M0.3 and widened with every slice that added a discovery surface.

**Decision:**

1. **A dependency, not middleware — and this contradicts a guideline, deliberately.**
   API_GUIDELINES said *"rate limiting per user at the middleware layer"*, but Starlette
   middleware runs **before** routing and dependency resolution, so no authenticated user
   exists there. "Per user" and "at the middleware layer" cannot both hold unless the token
   is verified a second time per request — duplicating the one dependency auth deliberately
   made single. The limiter is therefore `rate_limited(bucket)` in `auth/dependencies.py`,
   declared per route beside the role gates it resembles. The guideline is amended to say
   *dependency layer*.

2. **Order: authenticate → authorize → limit → service.** Three consequences, all wanted:
   the subject is the caller's PulseOS `user_id`; a caller refused by the role gate spends
   nothing; and the limiter runs **before the service resolves any Health ID**, so a 429
   cannot vary with whether a patient exists. That last property is structural, not merely
   tested.

3. **Four buckets, keyed `u:{user_id}`** — `patient_lookup` 20/60s (the only endpoint
   returning a name), `record_existence` 30/60s, `granted_records` 30/60s,
   `access_request_create` 10/60s. **Every outcome spends quota**: a 404 or 422 costs the
   same as a hit, because probing an ID that matches nobody is exactly the request an
   attacker makes, and counting successes alone would leave enumeration unthrottled.

4. **Fixed window, `INCR` + `EXPIRE NX` in one pipeline.** `INCR` is atomic and returns the
   post-increment value, so the read-then-write race cannot occur; `EXPIRE NX` rides along,
   so there is no round trip between counting and setting the lifetime. The window index is
   part of the key, which makes expiry a cleanup detail rather than a correctness one: a
   counter that somehow lost its TTL is never consulted again, so the worst case is a bounded
   memory leak, never a lockout. `Retry-After` is arithmetic — no extra round trip.
   A fixed window permits up to 2× the limit across a boundary; for a control measured in
   hundreds of requests that is irrelevant, and a sliding window would be sophistication
   without a reason.

5. **Fail-open**, following ADR-014's precedent that Redis is advisory here: an enqueue
   failure never fails the originating request, and neither does a limiter failure. A blip
   must not take consent requests, discovery and lookup offline; `/ready` reports Redis
   independently, so the outage stays visible. The outage log is throttled to one line per
   30s per process.

6. **429 reuses the existing problem+json path** — `HTTPException(429, headers={"Retry-After":
   ...})` through the handler that already propagates headers. Integer seconds. The body is
   **identical for every bucket and every caller**: no bucket name, no counts, no Health ID.
   A 429 must not become the side channel the limiter exists to close. Declared in OpenAPI on
   exactly the four protected operations.

7. **Configuration:** `PULSEOS_RATE_LIMIT_ENABLED` and `PULSEOS_RATE_LIMITS`, a JSON map of
   `bucket -> "limit/window"` overriding a typed default table. Malformed configuration
   raises at startup, never per request: a limit that silently fell back to a default because
   of a typo is a security control that lies.

**Scope, stated so the gap is not mistaken for coverage:** *M3-D protects authenticated abuse
on the four selected Health-ID/discovery surfaces. Unauthenticated/pre-authentication
throttling is deferred until trusted proxy/IP semantics and the deployment target are
established.* There is no `ProxyHeadersMiddleware` and no `forwarded_allow_ips`, so
`X-Forwarded-For` is fully client-controlled and **is not trusted**. IP keying is reserved in
the key format (`ip:{addr}`) and unimplemented; it is blocked on ADR-009.

**Consequences:** every future route opts in with one dependency, so M5's expensive AI
endpoints inherit throttling by declaration rather than by retrofit. Unauthenticated floods
still cost one Firebase verification each — a real remaining gap, recorded in TODO. Counters
are per bucket per user per window, and shared across API workers because Redis is shared.

**Amendment (2026-10-25 — Session 021; **accepted by the Product Owner 2026-10-25**): bucket
`audit_batch_verify` (30 / 60 s).** Applied to `GET /audit-batches/{batch_number}`, the one
audit read open to every authenticated role (ADR-027 amendment). It carries no PHI but recomputes
a whole sealed batch (up to 256 leaves) per call, so it is bounded like the other content reads.
Same keying, fail-open and 429 semantics as decisions 3–6. (The `ai_generate` and `ai_search`
buckets were added by the AI work and ADR-020 Amendment 1.)

---

## ADR-025 — The patient's audit trail attributes events to the hospital recorded on them

**Date:** 2026-09-08 · **Status:** Accepted (M4) · **Extends:** ADR-023

**Context:** ADR-023 captured `actor_hospital_id` at write time precisely so history would not
move when staff transfer, and used it to scope the hospital's own audit view. The patient's
view never received it. Instead the frontend rendered each event's origin from
`StaffDisplayResponse.hospitalName` — the actor's **current** affiliation, resolved by joining
`doctors.hospital_id`. That is the exact join ADR-023 exists to refuse, arriving by a different
route: a clinician changing jobs would silently re-attribute every past access in the patient's
trail to their new employer. Grouping the page by organisation would have promoted that from a
per-row mislabel to the page's primary structure.

**Decision:**

1. **`AuditEventResponse.actorHospital` (`{hid, name}`, nullable)**, resolved from the event's
   own `actor_hospital_id` via a batched lookup beside the existing actor projection. `hid`
   because grouping needs a stable key and a name is not one. Null has two truthful causes and
   no fallback: a patient acted (they belong to no organisation), or the event predates
   migration 0005. **Never substitute the actor's present hospital for either.**

2. **`StaffDisplayResponse` is unchanged and keeps its current-affiliation meaning.** The two
   answer different questions and both are needed: "where does this person work now" is what a
   patient weighs when granting access in the consent inbox; "which organisation did this" is
   what a historical log must say. Splitting them is the decision — not replacing one with the
   other.

3. **The patient UI groups on `actorHospital` only.** Events with none form a named
   *Unattributed activity* group; patient-actor events form *Your own activity*. Neither is
   merged into a hospital, and no hospital is inferred for them.

4. **No schema change, no new event, no hash change.** The column and its index landed in
   0005; `actor_hospital_id` is already inside the v2 hashed payload, and this adds a response
   field only. ADR-019's reserved v3 keccak transition is untouched.

**Why:** an audit trail that rewrites who accessed what, whenever someone changes employer, is
not evidence. The truthful column already existed and was already indexed; only the patient's
projection was missing it.

**Consequence:** the hospital named against pre-0005 events disappears from the patient's view,
replaced by an honest "unattributed". That is a visible regression in coverage and a correction
in accuracy — the previous value was a guess. Attribution is complete from September 2026.

---

## ADR-026 — (placeholder) Deferred per-event audit anchoring — text not yet written
**Status:** Documentation follow-up — **the original decision text has never existed in this file
and has not been recovered.** Commit `b17c2f0` (2026-10-04, "add deferred blockchain anchoring")
cites "ADR-026" in `consent/anchoring.py`, `anchor_service.py`, `models.py`, `repository.py`,
`router.py`, `schemas.py`, `errors.py`, `dependencies.py` and migration 0006, but no ADR was
recorded. Writing it is a separate task: it must document only behaviour verifiable in that code,
mark any principle inferred from code comments as inferred, and go to the Product Owner for
approval. ADR-027 lists the inferred behaviours it preserves and the one it supersedes.

---

## ADR-027 — Merkle-batched blockchain anchoring of v3 audit digests
**Date:** 2026-10-11 · **Status:** Accepted (M6; approved by the Product Owner 2026-10-11) ·
**Amends:** ADR-004 decision 2 · **Clarifies:** ADR-019 Resolution · **Builds on:** ADR-023 and
the existing anchoring behaviour cited as ADR-026 (unwritten — see its placeholder)

**Context:** ADR-004 makes PostgreSQL the authoritative audit store and a public chain a
tamper-evidence layer — hashes only, anchoring asynchronous and never on the clinical path — and
sketched one on-chain write per event carrying the event digest, event type and timestamp. That
shape costs gas in proportion to clinical activity, publishes the timing and type of each
patient's care, and cannot pass through the anchor port that exists in code:
`AuditAnchor.submit(digest)` accepts a bare 64-hex digest only (`require_digest`). M6.1 made new
audit events Keccak-256 (`hash_version` 3, ADR-019 Resolution); v1/v2 stay SHA-256 and locally
verifiable. M6.2/M6.2.1 added `consent/merkle.py`, a reviewed Merkle reference implementation with
pinned vectors and trusted-metadata proof verification. This ADR decides how v3 events are batched,
committed, persisted, published and reconciled.

**Decision:**

1. **Scope.** Only verified v3 audit events are chain-anchored, in **batches** — one Merkle root
   per batch, one 32-byte commitment per batch on-chain. Per-event on-chain anchoring is not
   built. No healthcare request waits on sealing, submission or reconciliation (ADR-004
   decision 3 stands).

2. **Versioned hashing.** v1/v2 digests remain SHA-256, verified under each row's own scheme
   (ADR-023); they are never rehashed, relabelled, deleted or admitted to a batch. A row enters a
   batch only through `V3Batch`, which requires a non-null UUID `id`, `hash_version == 3` and
   `recompute_event_hash(row) == row.event_hash`, and refuses the whole batch otherwise.
   `MerkleTree` over raw digests is never used directly for chain-bound data.

3. **Merkle construction — protocol version 1.** `consent/merkle.py` is the reference
   implementation; any other implementation, Solidity included, must reproduce its pinned vectors
   byte for byte. Keccak-256 (never SHA3-256). Leaf `keccak256(0x00 ‖ d)`, `d` = the 32 raw bytes of
   the event's v3 `event_hash`. Node `keccak256(0x01 ‖ left ‖ right)`, positional children (not
   sorted). An unpaired last node is promoted unchanged, never duplicated (equivalent to RFC 6962's
   tree hash). Empty batches refused; a single-leaf root is `keccak256(0x00 ‖ d)`; duplicate
   digests and duplicate event ids refused.

4. **Order.** Leaves are ordered `(occurred_at UTC ASC, id ASC)` once, at sealing, and the
   position is persisted as `leaf_index`. Thereafter the persisted index is authoritative; nothing
   re-sorts.

5. **Batch commitment — the only value published.**
   `C = keccak256(0x02 ‖ uint8 protocol_version ‖ uint64 batch_number ‖ uint32 leaf_count ‖ bytes32 root)`,
   packed and big-endian (46 input bytes); Solidity
   `keccak256(abi.encodePacked(bytes1(0x02), uint8(v), uint64(n), uint32(c), root))`. `0x02` is
   distinct from the leaf and node prefixes. `C` binds the protocol version, sequence number and
   leaf count, so none of them rests on a proof-supplied claim, and it is a 64-hex value, so the
   digest-only `AuditAnchor.submit(digest)` port is preserved unchanged. Pinned vectors (computed
   with pycryptodome and cross-checked with OpenSSL's `keccak-256`, built on `merkle.py`'s pinned
   roots):

   | v | n | c | root | C |
   |---|---|---|---|---|
   | 1 | 1 | 5 | `9649d2b3…d0cb1952` | `7d2d9dd7205f9adb892bd361857652127df7e954f3132228e7724aeb53476c36` |
   | 1 | 2 | 1 | `5f61df14…3188e313` | `dcf485fefd095822e3191e95048dfe944a8dcdc7e0412397a9fb1c53af8caa4c` |

6. **Proof verification.** A Merkle proof establishes membership under a root and nothing more;
   `MerkleProof.leaf_index`/`leaf_count` are claims. Positions and batch sizes are authoritative
   only from persisted batch metadata, passed as `trusted_leaf_index`/`trusted_leaf_count`. Full
   verification of one event: recompute its v3 digest from the row → verify the proof with the
   trusted index and count → recompute `C` from persisted `(protocol_version, batch_number,
   leaf_count, root)` → compare with the stored commitment and, once a receipt exists, the
   on-chain value. No inclusion proof is presented as evidence that a batch is complete.

7. **Existing per-event anchors.** `audit_anchors` and every historical row stay readable; none is
   deleted or rewritten. When batch sealing is introduced (M6.3), the old per-event workflow
   (`AuditAnchorService.anchor_event` / `anchor_pending`) stops admitting v3 events, so no new
   per-event anchor is created for one. Nor is one created for any event whose `hash_version` is
   unsupported or whose stored digest does not recompute under it. Three kinds of evidence are
   kept distinct and never substituted for one another:
   - **Historical per-event anchor verification.** A per-event `audit_anchors` row of any hash
     version — including a v3 event anchored per-event before M6.3 — keeps verifying through the
     existing per-event path (`AuditAnchorService` verdicts) as *historical per-event evidence*.
     A `local-dev` anchor is a simulation and proves no public-chain inclusion.
     **Amended 2026-10-25, approved by the Product Owner (see the ADR-027 amendment "Batch
     evidence takes precedence"): this no longer holds for v3.** A retained v3 per-event row is still stored, never deleted or
     rewritten, and still assessed — it can report `EVENT_ALTERED`/`ANCHOR_ALTERED` when it
     contradicts the event — but it can no longer establish `VERIFIED`; a matching row reads
     `NOT_ANCHORED`, and the event becomes `VERIFIED` only through batch membership once sealed.
     v1/v2 rows are unchanged.
   - **Merkle batch membership.** Established only by a membership row checked against its sealed
     batch's root using the persisted, trusted `leaf_index` and `leaf_count`.
   - **On-chain verification of a batch commitment.** Established only by comparing the stored
     commitment with the on-chain value referenced by the batch's receipt (deferred stage).

   A v3 event's *batch* anchoring status is derived from its batch membership, the batch metadata
   and the batch's receipt — never inferred from a per-event anchor. A per-event verdict is never
   presented as evidence of batch membership or of on-chain commitment verification, and batch
   membership is never presented as on-chain verification. Until the integrity API is updated
   (deferred), the existing per-event path reads `NOT_ANCHORED` for a batched v3 event that has no
   historical per-event anchor: accurate but incomplete, and not a verdict on the batch.

8. **Persistence (M6.3; additive tables only — `audit_logs` and `audit_anchors` unaltered).**
   *Batch* (immutable once written): `id`, `batch_number` (UNIQUE, contiguous from 1, assigned at
   sealing), `protocol_version`, `hash_version` (= 3), `leaf_count` (1 ≤ c ≤ configured maximum),
   `root`, `commitment`, the covered `occurred_at` range, `created_at`. *Membership* (immutable):
   `batch_id`, `audit_log_id` (**UNIQUE** — one batch per event, ever), `leaf_index` (UNIQUE per
   batch, contiguous `0..leaf_count-1`), `digest` as sealed. *Receipt* (append-only; deferred
   stage): `batch_id`, `network`, `reference` (tx hash), block number/time where available,
   `anchored_at`, UNIQUE `(batch_id, network)`.

9. **Verdicts are computed; evidence is persisted.** Batches, memberships and receipts are
   verification *evidence*, written once. Integrity verdicts stay computed on demand and are never
   stored as a mutable status. If reconciliation results are ever persisted, they are append-only
   evidence records, not a status column.

10. **Sealing.** Asynchronous; never blocks a healthcare request. Configurable settings, initial
    values: **maximum 256 leaves per batch**, **sealing interval 300 seconds**, **backlog threshold
    900 seconds**. A sealing run selects unbatched v3 events in canonical order up to the maximum,
    builds a `V3Batch`, assigns the next `batch_number`, computes `C`, and writes batch and members
    in **one transaction**. No eligible events → nothing written; empty batches are never created.
    UNIQUE `batch_number` and `audit_log_id` make a concurrent sealer fail and roll back rather than
    double-batch; a refused batch writes nothing. The scheduler that invokes sealing is not part of
    M6.3.

11. **Submission (deferred stage; requirements fixed now).** Separate from sealing and retry-safe:
    before resubmitting, the adapter checks whether `C` is already recorded on-chain; a duplicate of
    the same `C` is success. A batch whose submission keeps failing stays sealed and unanchored —
    never re-sealed or edited. Failures are logged with ids only.

12. **On-chain privacy boundary.** On-chain: the commitment `C`, and one minimal event from a
    write-restricted registry carrying `C` and at most what the contract needs to index it. Never
    on-chain: PHI, patient or Health IDs, event UUIDs, event types, raw audit records, per-event
    digests, leaf hashes or Merkle roots. **Acknowledged:** the transaction's sender address and
    its timing (block time, inclusion) are public and observable — they reveal the platform's
    anchoring cadence, not who or what was involved. Logs and errors carry ids only.

13. **Database-only reconciliation (M6.3; a library, no CLI).** Reports: **backlog** — v3 events
    without membership older than the backlog threshold (not tampering by itself); **membership
    integrity** per batch — member count = `leaf_count`, contiguous indices, every member's audit
    row exists and recomputes to the sealed digest, root rebuilt in `leaf_index` order equals the
    stored root, stored `C` equals recomputed `C`; **gaps** — `batch_number` contiguity; **late
    arrivals** — v3 events whose `occurred_at` falls within or before an already sealed range
    (backdated inserts); **unbatched event integrity** — every unbatched event, of any version, is
    recomputed under its own stored version: `UNSUPPORTED_HASH_VERSION` for a version no scheme
    defines (never reinterpreted), `EVENT_DIGEST_MISMATCH` for a stored digest that does not
    recompute (an edited row, or a relabel such as v3 → v2 without a matching digest); a
    consistent v1/v2 event is not a finding. Chain-side checks (stored `C` vs on-chain value;
    orphaned on-chain commitments) come with receipts. **Accepted limitations:** an event deleted
    *before* sealing leaves no trace, and an event relabelled *with* a consistently rewritten digest
    before sealing is indistinguishable from a genuine event of that version (ADR-023, qualified);
    the sealing interval bounds both windows, and database-level append-only enforcement (M7) would
    close them.

14. **Solidity requirements (no contract in this ADR).** `abi.encodePacked` exactly as in
    decision 5, never `abi.encode` (it pads). **Do not use OpenZeppelin `MerkleProof` /
    `StandardMerkleTree`** — sorted pairs (`commutativeKeccak256`), no node prefix and
    double-hashed leaves make it incompatible. Any on-chain proof verifier must handle promotion —
    derive sides from `(leafIndex, leafCount)` as `_path_shape` does, or take them explicitly;
    index bits alone are wrong (`(4, 5)` has one step, not three). Reject `leafCount == 0` and
    `leafIndex >= leafCount`. Take batch metadata from the commitment's preimage, never from a
    proof. The minimal contract is a write-restricted commitment registry; on-chain proof
    verification is optional and deferred.

**Existing behaviour cited as ADR-026 — what this ADR preserves and supersedes.** ADR-026 is
unwritten; the behaviours below are *inferred from code and its comments* (commit `b17c2f0`), not
from a recorded decision.

| Inferred existing behaviour | Under ADR-027 |
|---|---|
| Anchoring is deferred, never inline in a clinical request | **Preserved** (decision 10) |
| Integrity verdicts are computed on demand, never stored as a status | **Preserved** (decision 9) |
| Anchors are append-only evidence; one anchor per event, enforced by UNIQUE `audit_log_id` | **Preserved** in form — membership has UNIQUE `audit_log_id` (decision 8) |
| No backfill that misstates when an event was witnessed | **Preserved** — pre-M6.3 v3 rows are sealed by the first run with that run's time; v1/v2 never batched |
| No endpoint that triggers anchoring; no endpoint that verifies an arbitrary hash | **Preserved** — no API change |
| Patient verifies only events of their own trail | **Preserved** — no API change |
| `LocalChainAuditAnchor` is a network-free simulation without independent immutability | **Preserved** |
| Per-event anchoring: every event gets its own `audit_anchors` row via the sweep | **Superseded for v3 events** — batch membership + commitment instead; existing rows stay readable (decision 7) |

**Alternatives considered:** per-event anchoring (ADR-004's sketch) — gas grows with activity,
leaks per-event timing and type, would widen the digest-only port; rejected. Structured on-chain
fields `(batchNumber, root, leafCount, protocolVersion)` — more legible on an explorer but changes
the port and publishes batch sizes; rejected for `C`. Sorted-pair (OpenZeppelin-style) trees —
cannot express positions and conflict with the reference implementation; rejected. Bitcoin-style
odd-node duplication — `[a,b,c]` and `[a,b,c,c]` collide; rejected. Anchoring v1/v2 digests —
SHA-256, not verifiable by a Solidity contract, and would mix schemes in one protocol; rejected.

**Risks:** the pre-sealing window (decision 13); Amoy deprecation or outage (chain settings are
configuration, receipts are retry-safe, the local adapter works offline); key custody (environment
secret, testnet funds only); SQLite-vs-Postgres differences in UUID ordering, timestamps and
UNIQUE races — at least one Postgres integration run is required before the M6 gate; append-only
is enforced by convention, with database privileges/triggers an operations item
(docs/DATABASE_DESIGN.md principle 3).

**Testing strategy:** `merkle.py` vectors and the commitment vectors above are pinned and must be
reproduced by the contract's tests. Sealing: v3-only admission, contiguous numbering, unique
membership, a concurrent sealer losing cleanly, refusal writes nothing, no empty batch, maximum
enforced, per-event workflow refusing v3. Reconciliation: one tamper case per finding (edited row,
member, root, commitment; deleted member; batch-number gap; backdated insert). Migration
upgrade/downgrade in `test_alembic`. Existing integrity and anchoring tests stay green or are
updated only where decision 7 deliberately changes v3 behaviour.

**Migration considerations:** additive tables only, chained from the current head
(`aedb0169a4eb`); no backfill; v1/v2 rows remain outside batches permanently; downgrade drops only
the new tables.

**M6.3 scope (approved):** additive batch and membership tables; deterministic sealing; commitment
computation with pinned vectors; database-only reconciliation; the decision-7 refusal of v3 events
in the per-event workflow; migration and concurrency/idempotency tests.

**Deferred:** receipts and submission; Polygon Amoy adapter, wallet handling, gas policy; Solidity
contract and deployment; scheduler (arq cron or operator-run); reconciliation CLI and chain-side
checks; public API and frontend changes (closing the decision-7 transitional gap; presenting v1/v2
rows that will never be anchored); on-chain proof verification; database-level append-only
enforcement; writing ADR-026.

**Consequences:** one transaction per batch rather than per event; the chain shows opaque 32-byte
commitments plus unavoidable sender and timing metadata; every v3 event is verifiable end to end
against persisted, authoritative metadata; completeness is a reconciliation result, never a proof
property; the ADR-004 anchor port is unchanged.

**Implementation Addendum (2026-10-17 — commit `e350b2a`): developer audit-integrity CLI.**
A runnable CLI workflow (`scripts/audit_integrity.py`) was introduced to provide local batch sealing
and verification against the database:
- `seal`: Seals unbatched v3 audit events into a deterministic Merkle batch with Keccak-256 root (`--limit`).
- `verify-batch`: Verifies batch Merkle root and leaf memberships (`--batch-number` or `--all`).
- `verify-event`: Generates and verifies a Merkle membership proof for an individual audit event (`--event-id`).
- `reconcile`: Reconciles all audit batches and events across the database to detect tampering.
*Remaining gaps & deferred items:* The CLI currently lacks an environment safety guard; scheduled background
sealing daemon/scheduler, API v3 Merkle verification endpoint (`GET /audit-logs/{id}/verification` currently
checks only legacy per-event `audit_anchors`), patient UI verification integration, and external blockchain
anchoring (Polygon Amoy / M6.4 not authorized) remain deferred.

**Amendment (2026-10-25 — `278bbfc`, `c7e5359` and Session 021 follow-up fixes; **accepted by
the Product Owner 2026-10-25**, including the decision-7 change below): verification surfaces and
the inclusion rule.** Several items deferred
above now exist:
- `seal` is guarded by `ensure_sealing_safety` before any engine is created: postgresql/sqlite URL,
  explicit `PULSEOS_ENVIRONMENT` in {local, test, staging, production} (implicit default refused),
  `--confirm-env` equal to it, local ⇒ local host, staging/production ⇒ non-local host and never
  `localhost:5433`; exit code 2 on refusal. Read-only subcommands are unguarded.
- API: `GET /audit-logs` and `GET /audit-logs/{id}/verification` now report batch evidence for v3
  events; `GET /audit-logs/{id}/proof` returns the event's membership proof (patient, own events;
  404 for unsealed or foreign); `GET /audit-batches/{batch_number}` returns `VALID`/`TAMPERED`
  with findings.
- **VERIFIED requires Merkle inclusion on every verification surface.** List, detail and proof
  share `verify_stored_inclusion` (`consent/merkle.py`): stored members must be exactly
  `0 .. leaf_count-1`, form a valid tree, and the event's path must recompute to the stored root —
  in addition to digest recompute, member-digest match, leaf bounds and commitment rebuild. A
  member whose batch row is missing is `ANCHOR_ALTERED`; tampered membership yields a verdict
  (`ANCHOR_ALTERED`, `proof: null`), never HTTP 500.
- **Batch evidence takes precedence; a per-event anchor never makes a v3 event VERIFIED**
  (amends decision 7, final review 2026-10-25). With a membership row the batch decides,
  regardless of the `hash_version` label. Without one, an `audit_anchors` row can only report a
  contradiction for a v3 event; a matching row yields `NOT_ANCHORED`. Historical v3 per-event
  anchors (written between M6.1 and M6.3) stay stored, unmodified and readable, and can still
  surface a contradiction, but are no longer sufficient evidence of integrity; those events
  verify only after they are sealed into a batch (they remain eligible for sealing). Why: the
  application never writes v3 per-event anchors any more and the `local-dev` reference is a
  deterministic function of the digest, so a matching row is indistinguishable from a forgery.
  Residual (local-only): an unsealed v3 event relabelled v2 with a forged v2 anchor still
  verifies. None of these local checks — per-event anchors, Merkle inclusion or batch
  commitments — resists an attacker who can rewrite the database consistently; only the
  deferred external anchoring would.
- **`/audit-batches` is authenticated-any-role and rate limited** (`audit_batch_verify`, ADR-024
  amendment): roots and commitments are attestation material with no PHI; findings may name
  opaque audit-log ids.
- Patient portal: per-entry integrity badge and "View proof" dialog; copy says local Merkle batch.
Still deferred: scheduler, receipts, contract, chain adapter, on-chain submission and verification.
Commitments remain in the same database as the events; M6.4 is not authorized.

---

## ADR-028 — Local Ollama is the sole AI generation provider; redaction revisited
**Date:** 2026-10-11 · **Status:** Accepted — recorded from the Product Owner's direction of
2026-10-11 (documentation-alignment task), reflecting commit `c95494a` · **Supersedes in part:**
ADR-007 (provider choice and redaction requirement)

**Context:** ADR-007 chose Gemini (external) and required a redaction layer before every external
LLM call. The implementation moved to a local model: commit `c95494a` (2026-10-10) removed the
Gemini provider. ADR-007 was never amended, so the decision record and the code disagreed.

**Decision:**
1. Generation goes through the `AnswerGenerator` protocol (`ai/generation.py`). **Ollama with
   Qwen3:8B is the only supported real provider** (`ai/providers/ollama.py`); a deterministic fake
   exists for tests. Configuration: `PULSEOS_AI_PROVIDER` (`ollama` | `fake`),
   `PULSEOS_OLLAMA_BASE_URL`, `PULSEOS_OLLAMA_MODEL`, `PULSEOS_OLLAMA_TIMEOUT_SECONDS`.
2. **No separate redaction layer is implemented.** The only transformation is
   `sanitize_clinical_query`, which replaces Health IDs and phone numbers in the *question*;
   evidence text sent to the model is not redacted.
3. **Before any external inference provider is added**, a redaction and data-sharing decision
   must be made and recorded as a new ADR. The ADR-007 redaction requirement is not discarded —
   it is deferred to that decision.

**Consequences:** the privacy boundary is the Ollama host, not "no third party": if
`PULSEOS_OLLAMA_BASE_URL` points to another machine, clinical evidence travels there, and logs on
that host are outside PulseOS's control. Local inference reduces third-party exposure; it does not
remove privacy risk. SECURITY.md and AI_ARCHITECTURE.md describe the boundary as built.

---

## ADR-029 — Deterministic lexical retrieval; pgvector deferred
**Date:** 2026-10-11 · **Status:** Accepted — recorded from the Product Owner's direction of
2026-10-11 (documentation-alignment task), reflecting the implemented `ai` module · **Amends:**
ADR-002

**Context:** ADR-002 chose pgvector (with LangChain) for consent-scoped vector retrieval. The AI
layer that was built (commits `a7df8b4`…`ff5b3fe`, 2026-10-04 to 2026-10-08) ingests sanitized FHIR
resources and retrieves with deterministic token scoring; no embeddings are computed and no vector
column exists (migration `aedb0169a4eb`).

**Decision:**
1. Current retrieval is **deterministic lexical scoring** — token overlap with a fixed
   clinical-synonym table (`ai/retrieval.py`) — over `ai_chunks`.
2. **Consent scoping stays in the query**, as ADR-002 intended: `patient_id = P AND category_id
   IN (allowed categories)`, where a clinician's categories come from active grants and a patient's
   are all categories.
3. **pgvector and LangChain are deferred**, not rejected and not scheduled. No implementation date
   is promised. The `pgvector/pgvector:pg16` image is used by infrastructure, but the extension is
   not used by the application.

**Consequences:** retrieval is reproducible and testable without a model, but recall depends on
vocabulary overlap. Adopting embeddings later requires a migration, an embedding provider decision
(subject to ADR-028's rule for external providers) and a re-index.

---

## ADR-030 — Synthea FHIR R4 import and FHIR-based AI ingestion (proposed record of existing behaviour)
**Date:** 2026-10-11 · **Status:** **Proposed — needs Product Owner acceptance.** It records
behaviour that already exists in code; it is not a new design.

**Context:** synthetic clinical data comes from Synthea FHIR R4 bundles, and the AI layer ingests
FHIR resources. Neither has an ADR; the design lives in module docstrings
(`records/fhir_mapping.py`, `records/fhir_import.py`, `ai/ingestion.py`).

**Behaviour as implemented (verified 2026-10-11):**
1. `scripts/import_synthea.py` imports pinned Synthea patients. Mapped resource types:
   `AllergyIntolerance`, `Condition`, `DiagnosticReport` (claimed `Observation`s folded into it),
   `Immunization`, `MedicationRequest`, `Procedure`. `Encounter` is not a record. Three categories
   (`CONDITION`, `PROCEDURE`, `ALLERGY`) were added to the vocabulary for this mapping.
2. Idempotent and non-destructive: deterministic keys backed by UNIQUE constraints; insert-if-absent
   only.
3. Consent-neutral: writes records and sanitized FHIR objects, never grants, requests or audit
   events; records are `PATIENT_LOCKER` origin and pass through `consent.enforce` like any other.
4. The import can index each resource into the AI tables; `scripts/backfill_ai.py` indexes
   records already in storage.

**Open questions for acceptance:** whether `PATIENT_LOCKER` is the intended origin for imported
records long term; whether Phase B of the import (deferred, TODO.md) changes any of the above.

---

## ADR-031 — Notifications Module: in-app delivery, transactional persistence, and polling
**Date:** 2026-10-12 · **Status:** **Implemented** — shipped in `15b2d1b` (2026-10-14, pushed
to `origin/main`) at the Product Owner's direction. Written as "Proposed — awaiting Product Owner
review"; no separate formal acceptance of the ADR text is recorded. The decision text below is
unchanged; see *Implementation notes* at the end for where the shipped code differs from it.
· **Supersedes in part:** ADR-008 (the async notification delivery assumption)

**Context:** The consent lifecycle consists of critical workflow handoffs: a clinician petitions
for patient records (`ACCESS_REQUESTED`), a patient reviews and decides per category
(`CONSENT_APPROVED` or `CONSENT_REJECTED`), and a patient can withdraw consent at any time
(`CONSENT_REVOKED`). Currently, access requests arrive silently in the patient inbox
(`GET /access-requests/inbox`), and approvals/rejections/revocations are discovered by clinicians
only upon querying `GET /granted-records` or attempting a record read.

ADR-008 originally sketched a Redis-backed async job queue (via arq, ADR-014) for background tasks
including notifications. However, introducing an asynchronous worker queue for notifications
creates a distributed dual-write hazard between PostgreSQL and Redis: enqueuing before database
commit risks phantom notifications if the consent transaction rolls back, while enqueuing after
commit risks lost notifications if the process crashes. Furthermore, clinical workflow integrity
demands that a failed or rolled-back consent transaction must never leave behind a notification.
Additionally, healthcare privacy regulations (HIPAA, India DPDP Act 2023) dictate that notification
messages must never leak Protected Health Information (PHI) or ungranted clinical context to
unauthorized parties or administrative roles.

**Decision:**

1. **Delivery — in-app notifications only.**
   - No external delivery channels: no Firebase Cloud Messaging (FCM), Apple Push Notification
     service (APNs), SMS, or email providers (SES/SendGrid).
   - In-app delivery via dedicated notification centers in the Patient and Doctor web portals
     fulfills all clinical workflow requirements for MVP without external third-party credentials,
     network failure modes, delivery fees, or data-sharing privacy risks.

2. **Persistence and transactions — PostgreSQL same-transaction atomicity.**
   - Notifications are stored in PostgreSQL in a dedicated `notifications` table owned by the
     `notifications` module.
   - Notifications are created within the **exact same database transaction** as the triggering
     consent change (managed by FastAPI's `get_db_session` request-scoped `AsyncSession`).
   - **Transaction boundary guarantee:** If a consent transaction fails, raises a domain or
     validation error, or rolls back for any reason, the notification is rolled back atomically.
     No phantom notifications, orphaned records, or eventual-consistency lag can occur.
   - **Explicit supersession of ADR-008:** ADR-008's assumption that notifications run via arq/Redis
     is superseded. The async job queue is not used for notification creation or delivery.

3. **Notification events, triggers, and recipients:**
   Notifications are generated strictly for four consent lifecycle events:
   - `ACCESS_REQUESTED`: Triggered in `ConsentService.create_request()`. Recipient is the target
     **Patient** (`patient.user_id`).
   - `CONSENT_APPROVED`: Triggered in `ConsentService.approve_categories()` / `_decide()`. Recipient
     is the requesting **Doctor** (`doctor.user_id`).
   - `CONSENT_REJECTED`: Triggered in `ConsentService.reject_categories()` / `_decide()`. Recipient
     is the requesting **Doctor** (`doctor.user_id`).
   - `CONSENT_REVOKED`: Triggered in `ConsentService.revoke_grant()`. Recipient is the grantee
     **Doctor** (`doctor.user_id`).
   - **Decision batching:** A successful logical consent decision covering multiple categories
     creates **exactly one notification** for its recipient, generated outside the per-category loop.
     A failed or rolled-back transaction leaves no notification.
   - **Revocation idempotency:** `CONSENT_REVOKED` is emitted **strictly when a grant is newly
     revoked** (after `grant.revoked_at` is set, guarded by the existing check that returns early if
     `grant.revoked_at is not None`). Idempotent retry calls produce no duplicate notifications.
   - **Grant expiry produces no notification** in this version: passive expiry or sweep jobs do
     not emit notification rows.

4. **Doctor identity resolution seam:**
   - `ConsentRequest.requester_doctor_id` and `ConsentGrant.grantee_doctor_id` store `doctors.id`
     primary keys. Notifications are addressed to `recipient_user_id` (`users.id`).
   - Doctor IDs and User IDs are **not interchangeable**.
   - Direct cross-module queries from `notifications` to `records.doctors` are forbidden (system
     isolation rule 1).
   - Identity resolution is performed through a minimal method on the published directory seam
     (`ClinicianDirectory`, backed by `DoctorRepository.get_by_id(doctor_id)` in `records.directory`
     over the shared request session): `get_user_id_by_doctor_id(doctor_id: UUID) -> UUID | None`.

5. **Notification content, privacy, and structured references:**
   - **Generic administrative messages:** Notification messages contain purely administrative,
     non-identifying copy. They must never disclose diagnoses, clinical categories, document
     details, Health IDs (`health_id`), or unnecessary personal identifiers:
     * `ACCESS_REQUESTED`: Title: `"Access Request Received"`; Message: `"A doctor requested access to your health records."`
     * `CONSENT_APPROVED`: Title: `"Access Request Approved"`; Message: `"A patient approved your record access request."`
     * `CONSENT_REJECTED`: Title: `"Access Request Declined"`; Message: `"A patient declined your record access request."`
     * `CONSENT_REVOKED`: Title: `"Consent Grant Revoked"`; Message: `"A consent grant for patient records was revoked."`
     *(Specifically, `CONSENT_REVOKED` does not disclose the revoked category name).*
   - **Structured references:** The `notifications` table stores only the minimal references required
     for client routing and authorized navigation:
     * `reference_request_id: UUID | None` — links to the relevant access request.
     * `actor_doctor_id: UUID | None` — records the initiating clinician where relevant.
     * `actor_hospital_id: UUID | None` — records hospital context where relevant.
     Display names are not duplicated in the notification row; clients resolve display details on
     demand through existing authorized endpoints.
   - **Authorization invariant:** A stored reference **never bypasses normal authorization checks**.
     Navigating to a referenced request or record still executes full role gates, relationship checks,
     and `consent.enforce`.
   - **Logging discipline:** Structured application logs (`app/core/logging.py`) record only opaque
     identifiers (`notification_id`, `recipient_user_id`, `event_type`, `request_id`). Notification
     message text, patient identifiers, and names are excluded from logs.

6. **Database schema and deletion conventions:**
   - Follows PulseOS's identity-retention and tombstone conventions (docs/DATABASE_DESIGN.md
     principle 5). `recipient_user_id` uses standard `ForeignKey("users.id", nullable=False)`
     without `ON DELETE CASCADE`.
   - `notifications` table:
     * `id`: `UUID` primary key (`UUIDPrimaryKeyMixin`).
     * `recipient_user_id`: `UUID` (`ForeignKey("users.id")`, `NOT NULL`, indexed).
     * `event_type`: `VARCHAR(32)` (`NOT NULL`), values: `ACCESS_REQUESTED`, `CONSENT_APPROVED`,
       `CONSENT_REJECTED`, `CONSENT_REVOKED`.
     * `title`: `VARCHAR(120)` (`NOT NULL`).
     * `message`: `VARCHAR(255)` (`NOT NULL`).
     * `reference_request_id`: `Uuid()` (`nullable=True`).
     * `actor_doctor_id`: `Uuid()` (`nullable=True`).
     * `actor_hospital_id`: `Uuid()` (`nullable=True`).
     * `is_read`: `BOOLEAN` (`NOT NULL`, default `False`).
     * `read_at`: `DateTime(timezone=True)` (`nullable=True`).
     * `created_at` / `updated_at`: `DateTime(timezone=True)` (`TimestampMixin`).
   - Indexes:
     * `ix_notifications_recipient_unread_created`: `(recipient_user_id, is_read, created_at, id)` —
       serves unread count and unread-filtered inbox without sorting.
     * `ix_notifications_recipient_created`: `(recipient_user_id, created_at, id)` — serves keyset
       cursor pagination.

7. **API and authorization:**
   - **Role gates:** Restricted to `Role.PATIENT` and `Role.DOCTOR`.
   - **System admin invariant:** Per docs/SECURITY.md and docs/DOMAIN_MODEL.md, `Role.SYSTEM_ADMIN`
     and `Role.HOSPITAL_ADMIN` have zero access to notification endpoints (`403 Forbidden`).
   - **Strict ownership & 404-not-403 convention:** Users can list and mutate only notifications
     where `recipient_user_id == caller.user_id`. Accessing or mutating another user's notification
     returns `404 Not Found` (never `403 Forbidden`), preventing existence probing and enumeration.
   - **Endpoints (under `/api/v1`):**
     * `GET /api/v1/notifications`: Keyset cursor-paginated (`?cursor=&limit=&unreadOnly=`, limit
       capped at 100). Response: `{ "items": [...], "nextCursor": "..." }`.
     * `GET /api/v1/notifications/unread-count`: Returns `{ "unreadCount": int }` for badge display.
     * `POST /api/v1/notifications/{id}/read`: Marks a single notification as read (idempotent,
       sub-resource action matching API guidelines).
     * `POST /api/v1/notifications/mark-all-read`: Marks all unread notifications of caller as read.
   - **Error handling and schema:** RFC 7807 problem details on error; camelCase JSON serialization.

8. **Frontend delivery and interaction:**
   - Shared bell icon and notification drawer in `@pulseos/ui`, integrated into Patient and Doctor
     portal headers.
   - Polling of `/api/v1/notifications/unread-count` (recommended 30-second interval, plus window
     focus and navigation triggers).
   - No WebSockets and no Server-Sent Events (SSE).

9. **Audit separation and retention:**
   - **Convenience records, not audit evidence:** Authoritative, tamper-evident audit history
     remains `audit_logs` (Keccak-256 v3 digests, Merkle batch commitments per ADR-027). The
     `notifications` table is mutable (`is_read`, `read_at`) and carries no cryptographic hash
     chain or blockchain anchoring.
   - **Retention and erasure:** Notifications may be pruned or erased under DPDP right-to-erasure
     and user retention policies without affecting the immutable append-only audit trail.

**Transaction and Notification Flow:**

```
Client (Doctor / Patient)
       │
       ▼  HTTP Request (e.g., POST /api/v1/access-requests)
┌────────────────────────────────────────────────────────────────────────┐
│ FastAPI Dependency: get_db_session                                     │
│   async with sessionmaker() as session, session.begin():               │
│                                                                        │
│   ┌──────────────────────── consent module ────────────────────────┐   │
│   │ 1. Validate caller, permissions & requested categories         │   │
│   │ 2. Insert ConsentRequest & ConsentRequestCategory rows         │   │
│   │ 3. Append AuditLog row (action=ACCESS_REQUESTED)               │   │
│   │ 4. Dispatch notification via NotificationService/seam          │   │
│   └───────────────────────────────┬────────────────────────────────┘   │
│                                   │                                    │
│   ┌───────────────────────────────▼ notifications module ──────────┐   │
│   │ 5. Insert Notification (recipient=patient.user_id,             │   │
│   │    event=ACCESS_REQUESTED, unread=True, references)            │   │
│   │    into SAME session                                           │   │
│   └────────────────────────────────────────────────────────────────┘   │
│                                                                        │
│   6. Request handler returns cleanly                                   │
│   7. Transaction COMMITS atomically (all rows durable)                 │
│      [On any exception / failure: ROLLBACK rolls back all rows]        │
└────────────────────────────────────────────────────────────────────────┘
```

**Alternatives considered:**

- *Async job queue via arq / Redis (ADR-008 sketch):* Rejected due to dual-write atomicity failure
  modes (phantom notifications on rollback, lost notifications on crash), operational complexity of
  worker lifecycle, and unnecessary latency for a local in-app alert.
- *WebSockets / Server-Sent Events (SSE):* Rejected due to stateful connection management, proxy/
  gateway connection limits, heartbeat overhead, reconnection handling complexity in frontend, and
  unwarranted complexity for low-frequency consent events.
- *External Push (FCM / APNs) / Email (SES / SendGrid):* Rejected due to external credentials,
  third-party service costs, device token lifecycle maintenance, and the privacy hazard of leaking
  healthcare interaction timing and metadata to third-party push networks.
- *PostgreSQL NOTIFY / LISTEN:* Rejected because it bypasses application domain abstractions, does
  not work smoothly with connection poolers (PgBouncer in transaction mode), and is unsupported in
  the SQLite local test environment.

**Consequences and trade-offs:**

- *Transactional consistency:* Guarantees 100% consistency between consent actions, audit logging,
  and notifications with zero dual-write bugs.
- *Privacy preservation:* Generic administrative text prevents clinical data or ungranted categories
  from leaking across notification views.
- *Latency & UX:* Polling introduces slight delivery latency (up to 30 seconds), which is fully
  acceptable for consent workflows where review cycles are measured in minutes or days.
- *Database load:* Polling creates periodic lightweight queries on indexed columns; mitigated by
  an efficient composite index and dedicated `unread-count` endpoint.
- *Module coupling:* `consent` calls a `NotificationDispatcher` interface published by
  `notifications`. Both participate in the request's shared `AsyncSession` without violating Clean
  Architecture or direct cross-module table access.

**Testing requirements:**

1. *Transactional rollback test:* Inject a failure/exception immediately after notification insertion
   before handler return; assert that `consent_requests`, `audit_logs`, and `notifications` are all
   rolled back and zero rows remain.
2. *Decision batching test:* Verify that approving/rejecting multiple categories in a single request
   produces exactly one consolidated notification for the requesting clinician.
3. *Revocation idempotency test:* Verify that calling `revoke_grant` on an already-revoked grant
   does not create a second notification.
4. *Data privacy & copy tests:* Assert that notification `message` and `title` contain strictly
   generic administrative copy and no Health IDs, patient names, diagnoses, or category codes.
5. *Authorization & negative authz tests:*
   - Patient attempting to fetch or mark Doctor's notification returns `404 Not Found`.
   - Doctor attempting to fetch or mark Patient's notification returns `404 Not Found`.
   - `Role.SYSTEM_ADMIN` and `Role.HOSPITAL_ADMIN` receive `403 Forbidden` on all notification endpoints.
6. *Read status & pagination tests:* Verify `POST /read`, `POST /mark-all-read`, unread count, and
   cursor pagination over `(created_at, id)`.

**Migration considerations:**

- New Alembic revision (revision `0008`), chained directly from the current head (`0007`).
- Additive schema only: creates `notifications` table and indexes.
- Reversible: `downgrade()` drops the table cleanly.
- No historical backfill: notifications begin accumulating from deployment onward.

**Explicitly out-of-scope features:**

- FCM push notifications, APNs, SMS, email, or third-party webhooks.
- WebSockets or Server-Sent Events (SSE).
- Background worker (arq) processing for notifications.
- Passive grant expiry notifications or undecided request lapse notifications.
- Administrative (Hospital Admin / System Admin) notification streams.
- Emergency break-glass notifications (deferred to Phase 2 with its own ADR).

**Implementation notes (as shipped in `15b2d1b`; recorded 2026-10-14, verified against the code):**

- Migration `0008` creates `notifications`; the four endpoints, role gates (PATIENT and DOCTOR
  only), recipient scoping and the four event types match decisions 3, 6 and 7. A multi-category
  decision emits one notification (decision 3).
- **Deviation from the "Module coupling" consequence:** there is no `NotificationDispatcher`
  interface. `ConsentService` imports `notifications.models.Notification` and
  `notifications.repository.NotificationRepository` directly and receives the repository through
  `consent/dependencies.py`. The writes still share the request session and transaction.
- `CONSENT_REVOKED` sets no `reference_request_id` and records the grantee doctor as
  `actor_doctor_id`.
- The `notifications` module writes no log lines, which satisfies decision 5's logging rule
  trivially.
- Frontend: `@pulseos/ui` `NotificationBell` / `NotificationDrawer` / `useNotifications` poll
  every 30 s and refresh on window focus and visibility change. Used in the patient and doctor
  top bars; the hospital portal has none (out of scope above). Notification items do not link to
  the referenced request.

---

## ADR-032 — Consent-gated FHIR R4 Bundle export
**Date:** 2026-10-25 · **Status:** **Proposed — needs Product Owner approval.** Records behaviour
already in code (`2e05ee4`, consent re-check `0ea4bac`); final-review priority 5. **Extends:**
ADR-006, ADR-013, ADR-020 (scope-level audit rows)

**Context:** record metadata is FHIR-aligned (ADR-006) and Synthea FHIR R4 resources are imported
(ADR-030), but there was no way to take data out in a standard shape.

**Behaviour as implemented:**
1. `GET /api/v1/records/export/fhir` returns `application/fhir+json`: a Bundle of type
   `collection` with a `Patient` resource built from the database plus one entry per stored FHIR
   record (`fullUrl` `urn:uuid:{record.id}`). Builder: `records/fhir_export.py`.
2. Only records stored as `application/fhir+json` are exported; uploaded PDFs/images are excluded.
3. PATIENT: own records, all categories, hidden records included; `patientHealthId` must be absent
   (422 otherwise). DOCTOR: ACTIVE clinician, `patientHealthId` required, scope = currently granted
   categories, hidden records excluded; no grant → 403 + `ACCESS_DENIED`. HOSPITAL_ADMIN and
   SYSTEM_ADMIN → 403.
4. The doctor path re-checks consent after the object-storage reads and drops revoked categories
   (403 + `ACCESS_DENIED` if none remain). Hidden status is not re-checked after the reads.
5. One `RECORD_EXPORTED` audit event (new `AuditAction`; no target column, `patient_id` carries
   the subject) per successful export. Not rate-limited.
6. UI: patient portal "Export FHIR (JSON)" (Records header and Settings → Your Data) downloads
   `pulseos-fhir-export-YYYY-MM-DD.json`. No doctor UI.

**Not claimed:** conformance. Output is FHIR R4-*shaped*; tests check structure and references
only — no HL7 validator or `fhir.resources` validation.

**Open questions for approval:** whether a 403 (rather than API_GUIDELINES' 404-not-403 rule) is right for a doctor
with no grant; whether export should be rate-limited; whether HOSPITAL_ADMIN should export its own
uploads; whether doctor export needs a UI.

---

## ADR-009 — (placeholder) Deployment target: Render vs AWS
**Status:** Proposed — decide at M1 gate. Recommendation: Render (managed Postgres + Redis,
simplest path for students); AWS only if the team wants the learning curve.

## ADR-010 — (placeholder) Flutter app timing
**Status:** Proposed — decide at M1 gate. Recommendation: start Flutter in Month 4 *after* the
patient web portal stabilizes, reusing the proven API; web portal is the demo-critical patient
surface. Original plan had all four clients in Month 3, which overloads the single frontend lead.

## ADR-033 — Index uploaded text-layer PDFs for local AI retrieval
**Date:** 2026-10-25 · **Status:** Accepted (2026-10-26, PR #4). **Extends:** ADR-008, ADR-014, ADR-028, ADR-029.

**Context:** the `record_uploaded` job only logged, so uploads never reached AI retrieval and the
assistant relied on imported Synthea data. Uploads accept PDF, JPEG and PNG.

**Decision:**
1. The worker indexes **PDFs with a text layer only**, using `pypdf` (new runtime dependency,
   pure Python, BSD-3). Maximum 300 pages and 500,000 extracted characters per document. JPEG/PNG and
   scanned PDFs with no extractable text are not indexed — there is no OCR, and nothing claims
   otherwise (UI: "Not searchable by AI").
2. One job is one transaction; no row lock is held across the object read or extraction.
   Idempotency rests on the existing UNIQUE `ai_documents.record_id` (a losing concurrent
   delivery returns `ALREADY_INDEXED` via a savepoint).
3. `processing_status`: `INDEXED`; `FAILED` for no text / encrypted / unparseable (not retried)
   or storage failing on the last of 5 arq attempts; images stay `UPLOADED`. `PROCESSING` is
   never written (unobservable inside one transaction).
4. Access is unchanged: chunks carry patient and category and are read only through the existing
   consent-scoped, hidden-aware retrieval and the post-generation consent re-check.
5. No document text in logs: outcome codes and record ids only; `pypdf` and database-driver
   loggers pinned to WARNING.

**Consequences:** extracted text is PHI at rest in `ai_chunks` (as imported FHIR text already
is). Bounded extraction (300 pages / 500,000 characters) but no per-job CPU timeout beyond arq's
job timeout. Re-indexing on file replacement is not needed — record files are immutable.


## ADR-034 — Hospital verification lifecycle and administrative audit trail
**Date:** 2026-10-26 · **Status:** **Accepted** by the Product Owner 2026-10-26, after local
verification (service, HTTP and opt-in PostgreSQL concurrency tests) · **Amends:** ADR-015,
ADM-01 (migration 0009)

**Context:** hospitals were only PENDING or VERIFIED. A platform admin could not refuse a
registration or pause a verified hospital, and verification left no history beyond the latest
verifier. Hospital administrative actions have no patient, so they cannot go in `audit_logs`,
whose `patient_id` is NOT NULL (and stays so).

**Decision:**
1. `hospitals.verification_status` ∈ {PENDING, VERIFIED, REJECTED, SUSPENDED}.
2. SYSTEM_ADMIN-only endpoints: `POST /api/v1/hospitals/{hid}/verify|reject|suspend|reinstate`
   with optional body `{reason?: string ≤ 255}` (extra fields forbidden, blank → null), and
   `GET /api/v1/hospitals/{hid}/audit-logs` (newest first, keyset-paginated). 404 unknown HID,
   409 for a disallowed transition.
3. Every real transition writes one row to the new append-only `hospital_audit_logs` table
   (migration 0010: hospital_id FK, actor_user_id FK, action ∈ {VERIFIED, REJECTED, SUSPENDED,
   REINSTATED}, reason, occurred_at), in the same transaction as the status change and after
   `SELECT … FOR UPDATE` (with `populate_existing`) on the hospital row, so conflicting
   concurrent transitions serialise and only one writes an event.
4. A request whose target state already holds returns 200 and writes no event.
5. REJECTED is terminal.
6. Reinstatement keeps the original `verified_by_user_id`/`verified_at`; the REINSTATED event
   records who reinstated.
7. Anything other than VERIFIED blocks new hospital-level operations: record upload, admin
   Health-ID lookup, doctor registration, doctor activation, **new consent requests** and **new
   record-existence discovery** (`GET /records/existence`) by the hospital's clinicians (PO
   decisions 2026-10-26; both 409, checked before the Health ID is resolved, so the refusal is
   identical for every Health ID and reveals nothing about any patient). Doctor deactivation
   stays allowed.
8. Suspension never rewrites consent: existing grants, request history, and access by ACTIVE
   clinicians under an active, unexpired grant are untouched (reads, granted listings, AI
   answers and FHIR export all run on existing grants); the patient can still revoke. No
   grant is revoked automatically.
10. **Lock order.** Every status-dependent operation locks the hospital row *first*.
   Transitions take `SELECT … FOR UPDATE` (`populate_existing`); doctor activation and the
   new-request gate (`records.directory.ClinicianDirectoryService.hospital_accepts_new_requests`)
   take `FOR SHARE` (`HospitalRepository.get_by_id_for_share`) before touching anything else.
   Shared locks don't block each other; a transition waits for them, and they wait for an
   uncommitted transition and then see its result — so no ACTIVE doctor and no new request
   can be committed against a hospital that a concurrent transaction suspended. Neither
   activation nor the request gate holds another row lock when it takes the hospital lock,
   and transitions lock the hospital before writing anything, so the order cannot invert into
   a deadlock (both interleavings are exercised on PostgreSQL). Deactivation takes no
   hospital lock.
9. `/hospitals/me/audit-logs` (ADR-023) is registered ahead of `/hospitals/{hid}/audit-logs`.

**Transition matrix** (rows: current state; columns: action)

| From \ Action | verify | reject | suspend | reinstate |
|---|---|---|---|---|
| PENDING | → VERIFIED (VERIFIED event) | → REJECTED (REJECTED event) | 409 | 409 |
| VERIFIED | 200 no-op, no event | 409 | → SUSPENDED (SUSPENDED event) | 200 no-op, no event |
| SUSPENDED | → VERIFIED (REINSTATED event) | 409 | 200 no-op, no event | → VERIFIED (REINSTATED event) |
| REJECTED | 409 (terminal) | 200 no-op, no event | 409 | 409 |

**Verification (2026-10-26, local):** transition matrix, idempotency, audit atomicity and
`FOR UPDATE` blocking (`tests/test_organizations_*`, `test_hospital_lifecycle_postgres.py`);
activation vs. suspension in both interleavings, concurrent activations, and the request gate
waiting on a suspension (PostgreSQL; the race tests fail against the previous unlocked read);
suspended-hospital request and discovery policy over HTTP (`test_m3_gate.py`) and in the
services, including AI answers and FHIR export continuing under an existing grant
(`test_demo_ai_workflow.py`, `test_m3_gate.py`).

**Consequences / open items:** append-only and the allowed status values are application-
enforced (no trigger, no CHECK on `hospitals.verification_status`). Downgrading 0010 drops the
whole lifecycle history, and REJECTED/SUSPENDED rows would break pre-0010 code
(docs/DATABASE_DESIGN.md §Downgrade and recovery). Record upload, admin lookup and doctor
registration and existence discovery check status without a row lock (an operation racing a
suspension commits, or is answered, as if ordered just before it; none of them grants access).
The records-side 409 detail reads "Hospital is not verified yet." also when suspended. The
admin history panel shows the first page only.

## ADR-035 — Public-testnet anchoring of Merkle batch commitments (M6.4)
**Date:** 2026-10-26 · **Status:** **Accepted** by the Product Owner 2026-10-26 **for the design
and the local implementation only. Public-testnet deployment and on-chain transaction
verification remain pending** — no public chain anchor exists. Supersedes the earlier "M6.4
not authorized" notes (ADR-027 amendment, ROADMAP) for the scope accepted here.
**Verification status, kept separate:** (a) *implementation* — verified locally 2026-10-26:
contract tests (Foundry), adapter/service/CLI/API tests with a mocked RPC and an in-memory
chain, migration 0011 on SQLite and scratch PostgreSQL, and an opt-in end-to-end run on a
**local `anvil` EVM** (deploy → submit → confirm → contract re-read = VERIFIED); (b) *public
testnet deployment* — **not performed**: no contract is deployed on Amoy or Sepolia and no
public transaction exists. Nothing here is a production or mainnet deployment.
**Implements:** ADR-027 decisions 8, 11, 12, 14 ·
**Builds on:** ADR-004, ADR-027.

**Context:** M6.1–M6.3 seal v3 audit events into local Merkle batches with a commitment `C`
(ADR-027 decision 5), but commitments live in the same database as the events, so nothing
resists an attacker who can rewrite the database consistently. ADR-027 fixed the requirements
for public anchoring and deferred the contract, adapter, receipts and API.

**Decision:**
1. **Contract** `contracts/src/AuditCommitmentRegistry.sol` (Solidity 0.8.24, Foundry, no
   libraries): `anchor(bytes32 C)` callable only by an immutable `anchorer`; records
   `C → block.number`; emits `CommitmentAnchored(bytes32 indexed C)`; reverts on zero or
   already-recorded `C`; `anchoredBlock(C)` view; pure `computeCommitment(v, n, c, root)`
   reproducing ADR-027's pinned vectors (contract tests assert both vectors). Only `C` is ever
   on-chain — no root, digest, event id, patient or PHI (decision 12).
2. **Port** `consent/chain.py` `CommitmentRegistry`, separate from the per-event `AuditAnchor`
   port (a public chain's pending → mined → confirmed lifecycle does not fit a synchronous
   `submit → receipt`). Adapter `JsonRpcCommitmentRegistry`: plain JSON-RPC over `httpx`, local
   EIP-1559 signing with `eth-account` (new dependency). **Chain-id allow-list**: 80002 Polygon
   Amoy, 11155111 Sepolia, 31337 local dev — every other id (all mainnets) is refused before any
   request. The configured contract address is normalised to EIP-55 checksum form (a
   mixed-case address with a bad checksum is refused). Errors carry short codes only (never RPC bodies, URLs or keys); `httpx`/`httpcore`
   loggers are pinned to WARNING because they log request URLs, which embed provider keys.
3. **Persistence** — migration 0011, `audit_batch_anchors`: one row per (batch, network);
   chain id, contract, copied commitment, status PENDING/CONFIRMED/FAILED, tx hash, block,
   block time, failure code, timestamps. CHECKs: CONFIRMED ⇒ tx and block; PENDING ⇒ tx. This is
   an *operational submission record*, not an integrity verdict (ADR-027 decision 9 holds: the
   on-chain verdict is recomputed on every read). A CONFIRMED row is never rewritten; a FAILED
   one may be retried in place (deviation from decision 8's "append-only receipt", accepted
   because the chain itself is the immutable evidence).
4. **Submission** is operator-only: `scripts/audit_integrity.py anchor | anchor-refresh`, behind
   the same environment guard as `seal`. No API endpoint triggers submission. Before sending:
   local batch verification must pass (a tampered batch is never published), the RPC chain id
   must equal the configured one, a PENDING row is refreshed instead of re-sent, and the
   registry is asked whether `C` is already recorded — if so that record is adopted (retry-safe,
   decision 11). Refresh confirms only when the receipt succeeded, carries
   `CommitmentAnchored(C)` from the configured contract, has ≥ `chain_min_confirmations`
   (default 2), and contract state agrees on the block.
5. **Verification** `GET /api/v1/audit-batches/{n}/anchor` (any authenticated role, rate bucket
   `audit_batch_verify`, read-only) and `verify-chain` CLI: recompute `C` from the locally
   verified batch, read `anchoredBlock(C)` from the contract and, for a confirmed submission,
   re-read its receipt. Verdicts: NOT_CONFIGURED, UNAVAILABLE, LOCAL_INTEGRITY_FAILED,
   NOT_ON_CHAIN, VERIFIED, MISMATCH. A transaction hash alone is never reported as proof.
6. **UI**: the patient proof dialog shows local Merkle membership and public-chain anchoring as
   two separate sections; explorer links only for configured http(s) explorers.

**Alternatives considered:** web3.py (heavier, more surface than four RPC calls need);
Hardhat (Node toolchain + many packages vs. one Foundry binary); OpenZeppelin `Ownable`
(an immutable anchorer is simpler to audit; no ownership transfer needed).

**Risks / limitations:** no scheduler — sealing and anchoring are operator-run. One
confirmation-depth policy for all networks; a VERIFIED read right after inclusion could be
reorged on a testnet. An ambiguous broadcast failure is recorded FAILED; a retry adopts the
on-chain record if it landed, otherwise may send a second transaction (the contract rejects the
duplicate; gas only). Key custody is an environment secret on the operator's machine (testnet
funds only). The sender address and anchoring cadence are public. **Real public-testnet
deployment is not done** (no RPC endpoint, deployer key or test funds were available on
2026-10-26); the full flow is verified on a local `anvil` EVM (opt-in test).
