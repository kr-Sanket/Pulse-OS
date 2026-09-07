# API Guidelines

> Conventions for the PulseOS REST API. No concrete endpoints are defined here (design happens
> per milestone); every endpoint added must follow these rules.

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
  return 404, not 403. 409 for state conflicts (approving an already-revoked request); 422 validation.
- Pagination: cursor-based, `?cursor=&limit=` (max 100), response `{items, nextCursor}`.
  Offset pagination is not used.
- Filtering/sorting: explicit whitelisted query params only; sorting via `?sort=field` /
  `?sort=-field` (descending), whitelisted per endpoint.
- Timestamps: ISO 8601 UTC strings. Enums: SCREAMING_SNAKE strings.
- Every response echoes `X-Request-Id` (generated if absent) — the correlation key across
  logs and audit events. Rate-limited endpoints return `Retry-After` on 429.

## AuthN / AuthZ

- `Authorization: Bearer <Firebase ID token>` on every request except health/auth endpoints.
- Role (patient / doctor / hospital_admin) comes from verified custom claims — never from the
  request body.
- Every route declares its allowed roles via dependency; record/consent reads additionally pass
  the consent-enforcement dependency (SYSTEM_ARCHITECTURE.md §Isolation rule 3).
- Rate limiting per user at the **dependency** layer (Redis), declared per route beside the
  role gates — middleware runs before authentication, so per-user keying is impossible there
  (ADR-024). Stricter buckets on the Health-ID/discovery surfaces, and on AI endpoints when
  they land. Rate-limited operations declare `429` in the spec.

## Consistency & Safety

- Mutations that clients may retry (uploads, request creation) accept an `Idempotency-Key` header.
- State-changing endpoints are transactional: consent grant + audit event commit atomically.
- File uploads: client → API (validate, authorize) → S3; downloads only via short-lived presigned
  URLs from a dedicated endpoint that runs the consent check and writes the audit event first.
- Long-running work (OCR, summaries) returns `202 Accepted` + a status resource to poll
  (`processingStatus: uploaded|processing|indexed|failed`); never block a request thread on it.

## Documentation

- OpenAPI is generated from code and is the single source of truth; the web `api-client` package
  is regenerated from it in CI. If the spec diff is unintentional, the PR is wrong.
- Every endpoint has a docstring: purpose, roles allowed, consent requirement, failure modes.
