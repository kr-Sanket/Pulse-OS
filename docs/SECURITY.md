# Security

> PulseOS handles (synthetic) medical data, and its research claims rest on the security design
> being credible. We engineer as if the data were real, informed by HIPAA-style practices and
> India's DPDP Act 2023. Per-PR checks: `.claude/CHECKLIST.md` §Security.

## Threat Model (summary)

| Threat | Primary control |
|---|---|
| Doctor/hospital reads records without consent | Single consent-enforcement choke point on every content read; 404-not-403 for unauthorized existence probes |
| Consent/audit tampering (insider or attacker with DB access) | Append-only audit tables + on-chain hash anchoring + reconciliation job (ADR-004) |
| Stolen/leaked file URLs | Short-lived presigned URLs (minutes), issued only after consent check + audit write; private buckets, SSE on |
| Account takeover | Firebase Auth (OTP/Google), short-lived tokens, rate-limited auth endpoints |
| Role forgery | Roles from verified Firebase custom claims only — never from request payloads |
| ID enumeration | Opaque UUIDs/domain IDs; no sequential IDs; search returns existence only, rate-limited |
| PHI leakage to third parties | Redaction layer before every external LLM call (ADR-007); no PHI in logs, error trackers, or analytics |
| Prompt injection via record content (OCR'd text → LLM) | Records treated as data, not instructions: delimited/structured prompts, output constrained to schemas, copilot cannot trigger actions (read-only tool surface) |
| Dependency/supply chain | Lockfiles committed; Dependabot; CI audit step |

## AuthN / AuthZ

- Firebase ID token verified server-side on every request (provider evaluated and confirmed in
  ADR-011; all Firebase types confined to the `auth` module behind an internal port); roles
  (patient / doctor / hospital_admin / system_admin) live in custom claims set by the backend
  during onboarding.
- Deny by default, three ordered layers (ADR-013): static role gate → relationship check (own
  profile / own hospital / own upload) → consent grant via `consent.enforce`. Full permission
  matrix: docs/DOMAIN_MODEL.md §3.
- Hospital-admin actions are scoped to their own `HID`; doctors to their hospital affiliation.
- **System Admin never has access to medical content** — platform operations require no PHI and
  no admin break-glass path exists. This is an invariant, not a configuration.

## Data Protection

- **In transit:** HTTPS everywhere (including local-prod parity via compose profiles).
- **At rest:** S3 server-side encryption; Postgres volume encryption at the platform layer;
  secrets only via env (never committed — `.env.example` documents them with placeholders).
- **Field sensitivity:** health-profile fields (allergies, conditions, medications) are PHI —
  excluded from logs, error reports, and any external call unless redacted.
- **Erasure story (DPDP):** files and profile data are deletable; audit/consent rows are
  append-only, but contain no on-chain PHI and hashes only off-platform (ADR-004) — documented
  trade-off, defensible in the paper.

## Logging & Observability Hygiene

Structured logs with request IDs and actor IDs (opaque), never names/phone/health-profile
content/file names. Audit log ≠ debug log: the audit log is a product feature (patient-visible)
and an integrity-protected record; debug logs are ephemeral.

## AI-Specific Rules

See AI_ARCHITECTURE.md: redaction before external calls; consent-scoped retrieval as a query
predicate (no filter-after-search); explainer/copilot hard-refuse diagnosis/medical advice with a
fixed disclaimer; per-user quotas on LLM endpoints.

## Break-Glass / Emergency QR (Phase 2 — design before build)

The emergency QR exposes minimal data (blood group, allergies, critical meds, emergency contact)
without full consent flow. This is a deliberate, bounded consent exception and requires its own
ADR before implementation: unguessable rotating token in the QR, minimal fixed payload, every
scan audited and notified to the patient, expiry + patient kill-switch. Not in MVP.

## Secrets Inventory (maintained as they're added)

Firebase service account · Gemini API key · S3/MinIO credentials · Postgres/Redis URLs ·
anchoring wallet private key (testnet-only funds) · Sentry DSN. All env-injected; rotation is a
config change.
