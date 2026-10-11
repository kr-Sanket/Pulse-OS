# Security

> **Canonical source for security controls.** PulseOS handles synthetic medical data, but its
> research claims rest on the security design being credible, so every control below is marked
> **Implemented**, **Partial**, **Planned** or **Absent** as verified against the code on
> 2026-10-11. A planned control is *not* a protection. Per-PR checks: `.claude/CHECKLIST.md`.
> Informed by HIPAA-style practice and India's DPDP Act 2023.

## Threat model and control status

| Threat | Control | Status |
|---|---|---|
| Doctor/hospital reads records without consent | Single enforcement point `consent.enforce` on every non-owner record read (ADR-013); 404-not-403 for unauthorized existence probes | **Implemented** (covered by `tests/test_m3_gate.py` and consent tests) |
| A patient-hidden record reaches a grantee | Hidden records are excluded from existence, listing, read and download | **Implemented** for records — **Gap in AI:** AI retrieval ignores `is_hidden`, so a hidden record of a granted category can feed a clinician's AI answer (see §AI) |
| Consent/audit tampering by someone with DB write access | Append-only audit tables; versioned audit digests; Merkle batches + database-only reconciliation (ADR-027) | **Partial** — append-only is by **convention only** (no DB privileges or triggers; deferred to M7); reconciliation detects inconsistencies but not a consistent rewrite before sealing; **no on-chain anchoring yet** (M6.4+ unauthorized) |
| Stolen/leaked file URLs | Presigned URLs issued only after the consent check and audit write; lifetime `PULSEOS_S3_PRESIGN_TTL_SECONDS` (default 300 s); bucket created without a public policy | **Implemented** |
| Data at rest | S3 server-side encryption; database volume encryption | **Absent** — no SSE is requested by the storage adapter; local volumes are unencrypted; platform encryption depends on the undecided deployment target (ADR-009) |
| Data in transit | HTTPS | **Absent locally** (plain HTTP in development); production TLS depends on ADR-009 |
| Account takeover | Firebase Auth (ADR-011), server-side ID-token verification on every request | **Implemented**; rate limiting of auth endpoints is **Absent** |
| Role forgery | Role taken from the verified token's PulseOS custom claim (`pulseos_role`), never from request payloads | **Implemented** |
| ID enumeration / discovery abuse | Random Health IDs (ADR-012); per-user rate limits on `patient_lookup` (20/60 s), `record_existence`, `granted_records`, `access_request_create` (10/60 s) (ADR-024) | **Partial** — authenticated limits only; **pre-auth throttling Absent**; limiter **fails open** if Redis is unavailable |
| PHI sent to third parties | No external LLM; generation is local Ollama (ADR-028) | **Partial** — no redaction layer exists; only Health IDs and phone numbers are stripped from the *question*. Adding any external provider requires a new redaction decision first |
| Prompt injection via record content | Evidence passed as structured context; model output constrained to a JSON schema; AI endpoints are read-only (no tool or action surface) | **Partial** — no content filtering or injection testing |
| AI abuse / cost | `ai_generate` rate limit (10/60 s) on both answer endpoints | **Partial** — the clinician search endpoint is not rate-limited; no per-user quota |
| Secrets exposure | Environment variables only; `.env` and service-account files git-ignored; `.env.example` holds names and placeholders | **Implemented** |
| Dependency / supply chain | Lockfiles, Dependabot, CI audit step | **Partial** — `web/pnpm-lock.yaml` is committed; **no Python lockfile, no Dependabot, no CI dependency audit** |

## AuthN / AuthZ

- Firebase ID token verified server-side on every authenticated request; all Firebase types are
  confined to the `auth` module (ADR-011). Roles (`PATIENT`, `DOCTOR`, `HOSPITAL_ADMIN`,
  `SYSTEM_ADMIN`) come from the namespaced custom claim the backend sets during onboarding.
- Deny by default, three ordered layers (ADR-013): role gate → relationship check (own profile,
  own hospital, own upload) → consent grant via `consent.enforce`. Matrix: DOMAIN_MODEL.md §3.
- **System Admin never has access to medical content** — an invariant of the role. Note: no code
  path provisions a SYSTEM_ADMIN today (see TODO.md).

## Audit integrity

- Every consent decision, revocation, allowed read and denied read writes an audit event in the
  same transaction as the action (ADR-016…018, ADR-022).
- Digests are versioned (ADR-019, ADR-023): v1/v2 SHA-256 (historical, still verifiable), v3
  Keccak-256 for new events. Verified v3 events are sealed into Merkle batches with a 32-byte
  commitment; reconciliation is database-only (BLOCKCHAIN_ARCHITECTURE.md, ADR-027).
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
- **Error tracking (Sentry): Absent** — only a commented placeholder exists in `.env.example`.

## AI-specific rules

See AI_ARCHITECTURE.md. Implemented: consent-scoped retrieval as a SQL predicate, patient scope
limited to own records, `SUMMARY_GENERATED` audit event on generated answers, rate-limited answer
endpoints, local-only generation. **Known gap:** hidden records are not excluded from AI
retrieval. Not implemented: redaction layer, medical-advice refusal policy beyond the prompt, AI
quotas.

## Break-glass / emergency QR (Phase 2 — design before build)

Not implemented. The emergency QR would expose minimal data without the consent flow and requires
its own ADR first: unguessable rotating token, minimal fixed payload, every scan audited and
notified, expiry and patient kill-switch.

## Secrets inventory

Implemented and in use: Firebase service-account file path (`PULSEOS_FIREBASE_CREDENTIALS_FILE`),
S3/MinIO credentials, Postgres and Redis URLs. Reserved for later milestones and **not used by any
code**: chain RPC URL and anchoring-wallet private key (testnet-only), Sentry DSN. All
env-injected; rotation is a configuration change.
