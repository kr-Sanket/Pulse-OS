# Database Design — Principles & Conceptual Model

> Conceptual only, by design: physical schema (tables/DDL) is authored at M0–M3 via Alembic
> migrations, reviewed against this document. FHIR alignment rationale: ADR-006.

## Principles

1. **One PostgreSQL database**, module-owned schemas/tables (ADR-001). A module never queries
   another module's tables directly.
2. **Files never in the DB** — S3 keys + metadata only.
3. **Append-only where trust matters:** audit events and consent decisions are never UPDATEd or
   DELETEd; state changes are new rows (a revocation is an event, not an edit). Enforced by
   convention + DB privileges, verified by the chain reconciliation job (ADR-004).
4. **FHIR-aligned naming/shapes** (ADR-006): entities mirror FHIR resources so an export mapping
   is trivial — `Patient`, `Practitioner` (doctor), `Organization` (hospital),
   `DocumentReference` (record metadata), `Consent`, `AuditEvent`.
5. **Soft deletes only for user-manageable content** (e.g. a patient hiding a locker file);
   identity, consent, and audit data are never deleted (synthetic data makes this legally safe;
   the design still documents the DPDP-erasure story: only hashes are immutable, ADR-004).
6. **Every table:** UUID primary key, `created_at`/`updated_at` UTC. Domain-facing IDs
   (`PHI-IND-…`, `HID-…`) are unique business keys, not primary keys.
7. **Migrations:** Alembic, one migration per PR, reversible, reviewed. No manual DDL, ever.
8. **pgvector** embeddings table lives with record metadata so consent-scoped retrieval is a
   single SQL query (ADR-002); vectors reference the record chunk they came from.

## Conceptual Entity Map

```
Organization (hospital, HID-XXXX)
 ├─< Practitioner (doctor; role claims mirror auth)
 └─< DocumentReference (record metadata: category, status, S3 key,
      │                 uploading org, OCR/processing status)
      └─< RecordChunk ─ Embedding (pgvector)

Patient (Health ID PHI-IND-YYYY-NNNNNN, health profile, QR payload)
 ├─< DocumentReference (records are linked to exactly one patient)
 ├─< AccessRequest (from a practitioner/org; N requested categories)
 │    └─< ConsentDecision (per category: APPROVED | REJECTED; later REVOKED event)
 ├─< ConsentGrant (active view derived from decisions; what enforcement checks)
 └─< AuditEvent (append-only: who, what record/category, action, when, request context)
       └─ AnchorReceipt (chain tx hash + event hash, written by worker; nullable until anchored)
```

## Modeling Rules That Encode Product Semantics

- **Consent granularity** = (patient, requester, record **category**) — not per-file. Category is
  a controlled vocabulary table (FHIR `DocumentReference.type`-style codes), not a free string.
- **Existence vs content:** a doctor without consent may learn only that categories exist at
  which organization — model queries so this projection is expressible without exposing metadata
  (filenames, dates can leak information).
- **Revocation** must be O(1) to enforce: enforcement reads active grants, not the full decision
  history.
- **Audit events are written in the same transaction** as the authorization decision they record.
- **Processing status** on DocumentReference: `uploaded → processing → indexed | failed` (ADR-008).

## Explicitly Deferred

Physical DDL, indexes, and query plans (per-milestone work); family-account linkage (Phase 2);
partitioning/archival (out of scope at this data volume — noted in the paper as future work).
