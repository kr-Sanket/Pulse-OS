# API Guidelines

> Conventions for the PulseOS REST API. **The generated OpenAPI schema is authoritative** for
> routes, roles and shapes (`web/packages/api-client/openapi.json`, regenerated with
> `make api-client`). Rules marked *(not implemented)* are agreed conventions that no code
> enforces yet — do not rely on them as guarantees.

## Shape

- Base path `/api/v1`. Breaking changes require `/api/v2` — never mutate v1 semantics.
- Resources are plural kebab-case nouns: `/patients`, `/access-requests`, `/consent-grants`.
  Actions that don't map to CRUD use a verb sub-resource: `POST /consent-grants/{id}/revoke`.
- JSON bodies, `camelCase` fields (frontend-native); backend converts at the schema layer.
- Public identifiers are opaque (UUIDs or random domain IDs like `PHI-IND-2026-7K3M99X`,
  ADR-012) — never sequential integers in URLs (enumeration risk).

## Requests & Responses

- Validation at the boundary with Pydantic; unknown fields rejected on writes.
- Errors follow **RFC 7807** (`application/problem+json`): `type`, `title`, `status`, `detail`,
  `instance`, plus `errors[]` for field-level validation. One global exception handler — modules
  raise domain exceptions, never construct HTTP responses in services.
- Status codes: 200/201/204 conventionally; 401 unauthenticated; **403 vs 404 rule:** if the
  caller may not even know the resource exists (e.g. records of a patient with no consent),
  return 404, not 403. 409 for state conflicts (approving an already-revoked or expired request,
  a duplicate access request, an already-granted category, an unverified hospital); 422 validation
  (including an upload file name over 255 characters).
- Pagination: cursor-based, `?cursor=&limit=` (max 100), response `{items, nextCursor}`.
  Offset pagination is not used.
- Filtering/sorting: explicit whitelisted query params only; sorting via `?sort=field` /
  `?sort=-field` (descending), whitelisted per endpoint.
- Timestamps: ISO 8601 UTC strings. Enums: SCREAMING_SNAKE strings.
- Every response echoes `X-Request-Id` (generated if absent) — the correlation key across
  logs and audit events. Rate-limited endpoints return `Retry-After` on 429.

## AuthN / AuthZ

- `Authorization: Bearer <Firebase ID token>` on every request except health/auth endpoints.
- Role (patient / doctor / hospital_admin / system_admin) comes from verified custom claims — never
  from the request body. The token is verified with revocation checking, and every request
  re-reads the user row: a non-`ACTIVE` account gets 403 (`Account is suspended.`), and a DB
  role/`firebase_uid` that differs from the token gets 403. Expired, revoked or disabled tokens
  are 401; an unreachable or unconfigured Firebase project is 503.
- Every route declares its allowed roles via dependency; record/consent reads additionally pass
  the consent-enforcement dependency (SYSTEM_ARCHITECTURE.md §Isolation rule 3).
- Rate limiting per user at the **dependency** layer (Redis), declared per route beside the
  role gates — middleware runs before authentication, so per-user keying is impossible there
  (ADR-024). Buckets exist for the Health-ID/discovery surfaces, access-request creation, the
  two AI answer endpoints (`ai_generate`), the clinician AI search (`ai_search`) and the
  any-role batch verification read (`audit_batch_verify`, 30/60 s). FHIR export is not
  rate-limited.
  Rate-limited operations declare `429` in the spec.
  Unauthenticated routes are not rate-limited, and the limiter fails open if Redis is down.

## Consistency & Safety

- Mutations that clients may retry (uploads, request creation) accept an `Idempotency-Key`
  header. *(Not implemented — no endpoint reads this header today.)*
- State-changing endpoints are transactional: consent grant + audit event commit atomically.
- File uploads: client → API (validate, authorize) → S3; downloads only via short-lived presigned
  URLs from a dedicated endpoint that runs the consent check and writes the audit event first.
- Long-running work (OCR, summaries) returns `202 Accepted` + a status resource to poll
  (`processingStatus: uploaded|processing|indexed|failed`); never block a request thread on it.
  *(Not implemented — no `202` endpoints exist; AI answers are synchronous and bounded by the
  Ollama timeout.)*

## Documentation

- OpenAPI is generated from code and is the single source of truth; the web `api-client` package
  is regenerated from it with `make api-client` (manually). CI checks that the committed
  `schema.ts` matches the committed `openapi.json`, but does **not** re-export the spec from the
  backend (no Python lockfile, so CI could resolve different FastAPI/Pydantic versions). If the
  spec diff is unintentional, the PR is wrong.
- Every endpoint has a docstring: purpose, roles allowed, consent requirement, failure modes.

## Current surface (from the generated OpenAPI, 2026-10-25)

42 operations under `/api/v1`, plus `GET /health` and `GET /ready` (44 operations total). Roles and consent requirements
are in each operation's OpenAPI description.

| Area | Operations |
|---|---|
| auth | `GET /auth/me` |
| patients | `POST /patients/register` · `GET`/`PATCH /patients/me` · `GET /patients/lookup` |
| hospitals / doctors | `GET /hospitals` · `POST /hospitals/register` · `GET /hospitals/me` · `GET /hospitals/me/doctors` · `POST /hospitals/me/doctors/{doctor_id}/activate` · `POST /hospitals/me/doctors/{doctor_id}/deactivate` · `POST /hospitals/{hid}/verify` · `POST /doctors/register` · `GET /doctors/me` |
| records | `GET /record-categories` · `POST`/`GET /records` · `GET /records/existence` · `GET /records/{record_id}` · `POST /records/{record_id}/download-url` · `PATCH /records/{record_id}/visibility` · `GET /records/export/fhir` · `GET /granted-records` |
| consent | `POST /access-requests` · `GET /access-requests/inbox` · `GET /access-requests/sent` · `POST /access-requests/{request_id}/approve` · `POST /access-requests/{request_id}/reject` · `GET /consent-grants` · `POST /consent-grants/{grant_id}/revoke` |
| audit | `GET /audit-logs` · `GET /audit-logs/{audit_log_id}/verification` · `GET /audit-logs/{audit_log_id}/proof` · `GET /audit-batches/{batch_number}` · `GET /hospitals/me/audit-logs` |
| ai | `GET /ai/patients/{patient_id}/search` · `POST /ai/patients/{patient_id}/answer` · `POST /ai/me/answer` |
| notifications (ADR-031) | `GET /notifications` · `GET /notifications/unread-count` · `POST /notifications/{id}/read` · `POST /notifications/mark-all-read` |

There are no QR, summary/timeline, FHIR read/search API, on-chain receipt or chain-verification endpoints.
The hospital directory listing (`GET /hospitals`) is restricted to `SYSTEM_ADMIN`.

- **FHIR export** (`GET /records/export/fhir`, `application/fhir+json`): a Bundle of type
  `collection` (Patient resource + one entry per stored FHIR record). PATIENT exports their own
  records (all categories, hidden included; `patientHealthId` must be absent, else 422); an
  ACTIVE DOCTOR passes `patientHealthId` and gets only currently granted categories, hidden records
  excluded (no grant → 403 + `ACCESS_DENIED`). HOSPITAL_ADMIN and SYSTEM_ADMIN get 403. Uploaded
  PDFs/images are not included. One `RECORD_EXPORTED` audit event per successful export.
  FHIR R4-*shaped*; not validated against an HL7 validator.
- **Audit integrity:** `GET /audit-logs` items and `GET /audit-logs/{id}/verification` report
  `NOT_ANCHORED | VERIFIED | EVENT_ALTERED | ANCHOR_ALTERED`; for v3 batched events, `VERIFIED`
  requires Merkle inclusion against the stored batch root. `GET /audit-logs/{id}/proof` returns the
  event's membership proof (patient, own events only; 404 for unsealed or foreign events; on
  tampered membership it returns `ANCHOR_ALTERED` with `proof: null`, not a 500).
  `GET /audit-batches/{batch_number}` is open to **any authenticated role** by design (roots and
  commitments carry no PHI) and returns `VALID`/`TAMPERED` with findings. All of this is local
  database evidence — nothing is anchored on a public chain (BLOCKCHAIN_ARCHITECTURE.md).

