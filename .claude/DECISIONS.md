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

## ADR-009 — (placeholder) Deployment target: Render vs AWS
**Status:** Proposed — decide at M1 gate. Recommendation: Render (managed Postgres + Redis,
simplest path for students); AWS only if the team wants the learning curve.

## ADR-010 — (placeholder) Flutter app timing
**Status:** Proposed — decide at M1 gate. Recommendation: start Flutter in Month 4 *after* the
patient web portal stabilizes, reusing the proven API; web portal is the demo-critical patient
surface. Original plan had all four clients in Month 3, which overloads the single frontend lead.
