# Security

> **Canonical source for security controls.** PulseOS handles synthetic medical data, but its
> research claims rest on the security design being credible, so every control below is marked
> **Implemented**, **Partial**, **Planned** or **Absent** as verified against the code on
> 2026-10-11 (notification and lookup rows added 2026-10-14; lookup, AI-search and consent
> rows updated 2026-10-15 after the authorization and audit correctness fixes; account-status,
FHIR-export, consent-revalidation and audit-verification rows updated 2026-10-25). A planned control is *not* a protection. Per-PR checks: `.claude/CHECKLIST.md`.
> Informed by HIPAA-style practice and India's DPDP Act 2023.

## Threat model and control status

| Threat | Control | Status |
|---|---|---|
| Doctor/hospital reads records without consent | Single enforcement point `consent.enforce` on every non-owner record read (ADR-013); 404-not-403 for unauthorized existence probes | **Implemented** (covered by `tests/test_m3_gate.py` and consent tests) |
| A patient-hidden record reaches a grantee | Hidden records are excluded from existence, listing, read and download | **Implemented**, including clinician AI retrieval (search, answer context and citations), which filters `is_hidden` in the query before scoring and the result limit. Answers delivered before a record was hidden cannot be recalled (see §AI) |
| Consent/audit tampering by someone with DB write access | Append-only audit tables; versioned audit digests; Merkle batches + database-only reconciliation (ADR-027) | **Partial** — append-only is by **convention only** (no DB privileges or triggers; deferred to M7); reconciliation detects inconsistencies but not a consistent rewrite before sealing; **no on-chain anchoring yet** (M6.4+ unauthorized) |
| Stolen/leaked file URLs | Presigned URLs issued only after the consent check and audit write; lifetime `PULSEOS_S3_PRESIGN_TTL_SECONDS` (default 300 s); bucket created without a public policy | **Implemented** — **known limitation:** a URL already issued stays valid until its TTL even after the grant is revoked or the record hidden; it cannot be recalled |
| Revocation racing a long read (AI, export) | AI search and doctor AI answers re-check grants after retrieval/generation and drop revoked categories; the doctor FHIR export re-checks after its object-storage reads; a fully revoked result is refused and audited `ACCESS_DENIED` (see §AI-specific rules) | **Implemented** — the export does not re-check *hidden* status after its reads |
| Hospital admin reads a record the patient has hidden | Hospital admins keep layer-2 access (ADR-013) to records their hospital uploaded, audited, **including hidden ones** | **Confirmed policy** (Product Owner, 2026-10-25); disclosed to the patient under the hide control |
| Data at rest | S3 server-side encryption; database volume encryption | **Absent** — no SSE is requested by the storage adapter; local volumes are unencrypted; platform encryption depends on the undecided deployment target (ADR-009) |
| Data in transit | HTTPS | **Absent locally** (plain HTTP in development); production TLS depends on ADR-009 |
| Account takeover / suspended accounts | Firebase Auth (ADR-011), server-side ID-token verification on every request with `check_revoked=True`; every request re-reads the user and requires `ACTIVE` status and DB role/`firebase_uid` equal to the token claims (403 otherwise); expired/revoked/disabled tokens 401; Firebase unavailable 503 | **Implemented**; there is **no API** to suspend a user or revoke tokens (done out-of-band in the database/Firebase); rate limiting of auth endpoints is **Absent** |
| Role forgery | Role taken from the verified token's PulseOS custom claim (`pulseos_role`), never from request payloads | **Implemented** |
| ID enumeration / discovery abuse | Random Health IDs (ADR-012); per-user rate limits on `patient_lookup` (20/60 s), `record_existence`, `granted_records`, `access_request_create` (10/60 s) (ADR-024) | **Partial** — authenticated limits only; **pre-auth throttling Absent**; limiter **fails open** if Redis is unavailable. `GET /patients/lookup` (which returns a name) requires a VERIFIED hospital since 2026-10-15 — a self-registered PENDING admin gets 409 before the Health ID is even parsed (ADR-021 amendment); the lookup is still unaudited. Since 2026-10-26 (ADR-034) a doctor of a non-VERIFIED (e.g. SUSPENDED) hospital gets the same kind of 409 from `GET /records/existence` and `POST /access-requests`, before the Health ID is resolved |
| Audit-batch verification abuse | `GET /audit-batches/{n}` is open to any authenticated role (roots and commitments are attestation material, no PHI; findings may name opaque audit-log ids) and rate-limited by `audit_batch_verify` (30/60 s) | **Implemented** |
| Notification leakage | In-app notifications carry fixed generic text (no names, Health IDs, categories or diagnoses); recipient-scoped queries; 404 for another user's notification; PATIENT/DOCTOR only (ADR-031) | **Implemented** (`tests/test_notifications_*`, `test_consent_notifications_contain_no_phi_or_sensitive_identifiers`) |
| PHI sent to third parties | No external LLM; generation is local Ollama (ADR-028) | **Partial** — no redaction layer exists; only Health IDs and phone numbers are stripped from the *question*. Adding any external provider requires a new redaction decision first |
| Prompt injection via record content | Evidence passed as structured context; model output constrained to a JSON schema; AI endpoints are read-only (no tool or action surface) | **Partial** — no content filtering or injection testing |
| AI abuse / cost | `ai_generate` rate limit (10/60 s) on both answer endpoints; `ai_search` (30/60 s) on the clinician search | **Partial** — per-user windows only; no longer-term quota |
| Duplicate or racing consent writes | 409 for a request that duplicates an active grant or an open unanswered request, and for approving a category already actively granted; a per-(patient, clinician) PostgreSQL advisory lock serialises those checks; only UNIQUE violations map to 409 | **Implemented** — races validated on PostgreSQL 16 (`tests/test_consent_postgres.py`, opt-in; run by the CI `backend-postgres` job, reported passing in run #17 for `d09d721`) |
| Stale consent requests answered late | Expiry enforced on every decision; the PENDING → EXPIRED transition is committed by the refusal (ADR-017 amendment); listings report a past-deadline request as EXPIRED | **Implemented** — expiry is still lazy (no sweep); the stored row changes only when someone tries to answer it |
| Secrets exposure | Environment variables only; `.env` and service-account files git-ignored; `.env.example` holds names and placeholders | **Implemented** |
| Dependency / supply chain | Lockfiles, Dependabot, CI audit step | **Partial** — `web/pnpm-lock.yaml` is committed; **no Python lockfile, no Dependabot, no CI dependency audit** |

## AuthN / AuthZ

- Firebase ID token verified server-side on every authenticated request, including the revocation
  check; all Firebase types are confined to the `auth` module (ADR-011). The DB user must be
  `ACTIVE` and match the token's role and UID; a registration retry by an existing non-`ACTIVE`
  user is refused as suspended. Portals detect the `Account is suspended.` 403 and show a
  suspension message instead of routing to registration. Roles (`PATIENT`, `DOCTOR`, `HOSPITAL_ADMIN`,
  `SYSTEM_ADMIN`) come from the namespaced custom claim the backend sets during onboarding.
- Deny by default, three ordered layers (ADR-013): role gate → relationship check (own profile,
  own hospital, own upload) → consent grant via `consent.enforce`. Matrix: DOMAIN_MODEL.md §3.
- **System Admin never has access to medical content** — an invariant of the role (FHIR export
  returns 403 to SYSTEM_ADMIN and HOSPITAL_ADMIN). SYSTEM_ADMIN is provisioned only by the local
  CLI `scripts/dev_provision_system_admin.py`.

## Audit integrity

- Every consent decision, revocation, allowed read and denied read writes an audit event in the
  same transaction as the action (ADR-016…018, ADR-022).
- Digests are versioned (ADR-019, ADR-023): v1/v2 SHA-256 (historical, still verifiable), v3
  Keccak-256 for new events. Verified v3 events are sealed into Merkle batches with a 32-byte
  commitment; reconciliation is database-only (BLOCKCHAIN_ARCHITECTURE.md, ADR-027).
- Patient-facing verification (`GET /audit-logs`, `/audit-logs/{id}/verification`,
  `/audit-logs/{id}/proof`) reports `VERIFIED` for a batched v3 event only when its digest
  recomputes **and** its Merkle path against the stored batch root verifies; tampered membership
  yields `ANCHOR_ALTERED`, never a 500. Sealing is manual via the CLI, guarded by an explicit
  environment confirmation (`--confirm-env`).
- **What this does not provide yet:** independent, public-chain evidence. Nothing is submitted to
  any chain; local-dev anchors are a simulation. A consistent rewrite of an unsealed event, or
  deletion before sealing, is undetectable with database evidence alone.

## Data protection

- Files never in the database; S3 keys and metadata only (ADR-005). Uploads capped by
  `PULSEOS_RECORDS_MAX_UPLOAD_BYTES` (default 15 MiB).
- Health-profile fields (allergies, conditions, medications) are PHI — excluded from logs.
- **Erasure (DPDP):** files and profile data are deletable by design; audit and consent rows are
  append-only. No PHI is placed on-chain — only an opaque batch commitment is designed for
  publication (ADR-027) — so erasure stays satisfiable. This trade-off is documented, not solved.

## Logging and observability

- Structured JSON logs carry the request id; the rule is opaque IDs only — no names, phone
  numbers, health-profile content, filenames or bodies (`app/core/logging.py`). This is enforced
  by convention and review, not by an automated filter.
- `X-Request-Id` is client-supplied; it is sanitized and length-capped before it is stored on
  audit events.
- The audit log is a patient-visible product feature; debug logs are ephemeral.
- Database-driver and PDF-parser loggers (`sqlalchemy.engine`, `sqlalchemy.pool`, `aiosqlite`,
  `asyncpg`, `pypdf`) are pinned to WARNING by `configure_logging` whatever the root level:
  they emit bound SQL parameters or raw document bytes, so `PULSEOS_LOG_LEVEL=DEBUG` must not
  turn them on (branch `feature/upload-ai-indexing`). The indexing worker logs record ids and
  outcome codes only.
- **Error tracking (Sentry): Absent** — only a commented placeholder exists in `.env.example`.

## AI-specific rules

See AI_ARCHITECTURE.md. Implemented: consent-scoped retrieval as a SQL predicate, patient scope
limited to own records, `SUMMARY_GENERATED` audit event on generated answers, rate-limited answer
endpoints, local-only generation, and exclusion of patient-hidden records from clinician
retrieval. The patient's own copilot still includes their hidden records (owner access). An
answer already delivered cannot be recalled after a record is hidden. The clinician search
endpoint (raw chunk text) is rate-limited (`ai_search`) and writes one audit event per request
(`RECORDS_SEARCHED` — its own action, distinct from a granted-records listing — or
`ACCESS_DENIED` with no scope; ADR-020 amendments). **Consent revalidation:** AI search re-checks grants after retrieval; a doctor answer with no live
grant never calls the model and writes `ACCESS_DENIED`; after generation, if any evidence category
was revoked or cannot be mapped (fail closed), the answer and citations are discarded,
`ACCESS_DENIED` is written and `SUMMARY_GENERATED` is not. A granted scope with no matching
evidence, and operational failures (502/503/504), write no audit row.
**Still open:** the search query travels in
the URL query string — the application's access log omits query strings, but intermediaries may
log them. Not implemented: redaction layer, medical-advice refusal policy
beyond the prompt, AI quotas.

## Break-glass / emergency QR (Phase 2 — design before build)

Not implemented. The emergency QR would expose minimal data without the consent flow and requires
its own ADR first: unguessable rotating token, minimal fixed payload, every scan audited and
notified, expiry and patient kill-switch.

## Secrets inventory

Implemented and in use: Firebase service-account file path (`PULSEOS_FIREBASE_CREDENTIALS_FILE`),
S3/MinIO credentials, Postgres and Redis URLs. Reserved for later milestones and **not used by any
code**: chain RPC URL and anchoring-wallet private key (testnet-only), Sentry DSN. All
env-injected; rotation is a configuration change.
