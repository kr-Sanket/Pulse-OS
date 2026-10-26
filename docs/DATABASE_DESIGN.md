# Database Design — Principles & Conceptual Model

> Principles and the conceptual model. **The physical schema is authoritative in the Alembic
> migrations (`backend/alembic/versions/`) and the ORM models**, summarized in §Physical tables
> below (verified 2026-10-11). FHIR alignment rationale: ADR-006.

## Principles

1. **One PostgreSQL database**, module-owned schemas/tables (ADR-001). A module never queries
   another module's tables directly.
2. **Files never in the DB** — S3 keys + metadata only.
3. **Append-only where trust matters:** audit events, consent decisions, anchors and batch rows
   are never UPDATEd or DELETEd; state changes are new rows (a revocation is an event, not an
   edit). **Enforced by convention and code review only** — there are no database privileges or
   triggers yet (deferred to M7). Database-only reconciliation detects many inconsistencies
   (ADR-027) but not a consistent rewrite before sealing; on-chain anchoring is not implemented.
4. **FHIR-aligned naming/shapes** (ADR-006): entities mirror FHIR resources so an export mapping
   is trivial — `Patient`, `Practitioner` (doctor), `Organization` (hospital),
   `DocumentReference` (record metadata), `Consent`, `AuditEvent`.
5. **Soft deletes only for user-manageable content** (e.g. a patient hiding a locker file);
   identity, consent, and audit data are never deleted (synthetic data makes this legally safe;
   the design still documents the DPDP-erasure story: only hashes are immutable, ADR-004).
6. **Every table:** UUID primary key and UTC `created_at`; mutable tables also carry
   `updated_at`, append-only tables deliberately do not. Domain-facing IDs (`PHI-IND-…`,
   `HID-…`) are unique business keys, not primary keys.
7. **Migrations:** Alembic, one migration per PR, reversible, reviewed. No manual DDL, ever.
8. **AI data lives with record metadata** so consent-scoped retrieval is a single SQL predicate:
   `ai_documents` / `ai_chunks` reference the record, patient and category. **No embeddings or
   pgvector columns exist** — retrieval is lexical (ADR-029).

## Conceptual Entity Map

```
Organization (hospital, HID-XXXX)
 ├─< Practitioner (doctor; role claims mirror auth)
 └─< DocumentReference (record metadata: category, status, S3 key,
      │                 uploading org, OCR/processing status)
      └─< AIDocument ─< AIChunk (text + content hash; no embedding — ADR-029)

Patient (Health ID PHI-IND-YYYY-XXXXXXC per ADR-012, health profile, QR payload)
 ├─< DocumentReference (records are linked to exactly one patient)
 ├─< AccessRequest (from a practitioner/org; N requested categories)
 │    └─< ConsentDecision (per category: APPROVED | REJECTED; later REVOKED event)
 ├─< ConsentGrant (active view derived from decisions; what enforcement checks)
 └─< AuditEvent (append-only: who, what record/category, action, when, request context)
       ├─ AuditAnchor (historical per-event anchor; v1/v2 events only since ADR-027)
       └─ AuditBatchMember ─> AuditBatch (v3 events sealed into Merkle batches; commitment C)
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
- **Processing status** on DocumentReference: `UPLOADED → PROCESSING → INDEXED | FAILED` is
  modeled (ADR-008), but only `UPLOADED` is ever written — no worker advances it yet.

## Physical tables (from migrations and models, 2026-10-26)

| Migration | Tables |
|---|---|
| `0001` | `users`, `patients` |
| `0002` | `hospitals`, `record_categories` |
| `0003` | `doctors`, `hospital_admins`, `medical_records` |
| `0004` | `consent_requests`, `consent_request_categories`, `consent_decisions`, `consent_grants`, `audit_logs` |
| `0005` | adds `actor_hospital_id` and `hash_version` to `audit_logs` (ADR-023) |
| `0006` | `audit_anchors` (per-event anchors) |
| `aedb0169a4eb` | `ai_documents`, `ai_chunks` |
| `0007` | `audit_batches`, `audit_batch_members` (ADR-027) |
| `0008` | `notifications` (ADR-031) |
| `0009` | adds nullable `verified_by_user_id` (FK → `users`) and `verified_at` to `hospitals`; set only on the PENDING → VERIFIED transition, so hospitals verified before 0009 keep NULL |
| `0010` | `hospital_audit_logs` (ADR-034, accepted): append-only lifecycle events per hospital; no schema change to `hospitals` — REJECTED/SUSPENDED are new values of the existing VARCHAR `verification_status` |
| `0011` (head) | `audit_batch_anchors` (ADR-035, accepted for local implementation): one public-chain submission row per (batch, network) |

20 tables in total; there are no timeline, summary or embedding tables. `notifications` is a
mutable convenience table (`is_read`, `read_at`), not audit evidence. Hospital lifecycle
transitions are recorded in `hospital_audit_logs`, never in `audit_logs` (whose `patient_id`
stays NOT NULL). Batch
constraints that the sealing design depends on — UNIQUE `batch_number`, `commitment`,
`audit_log_id` and `(batch_id, leaf_index)`, plus CHECKs on `batch_number`, `leaf_count`,
`hash_version` and `leaf_index` — are listed in BLOCKCHAIN_ARCHITECTURE.md and pinned by
`tests/test_alembic.py` and the opt-in `tests/test_alembic_postgres.py`.

## Downgrade and recovery (0010, 0011) — read before any rollback

Downgrades are tested only on scratch databases (SQLite and a disposable PostgreSQL 16); that
is not evidence of production safety. Run any migration against a copy of real data first.

- **`0011 → 0010`** drops `audit_batch_anchors`: every recorded submission (tx hash, block,
  status) is lost locally. Commitments already on-chain are unaffected, and re-running
  `scripts/audit_integrity.py anchor` after re-upgrading adopts them from the chain (it checks
  `anchoredBlock(C)` before sending), but historical FAILED/PENDING rows are gone.
- **`0010 → 0009`** drops `hospital_audit_logs`: **the entire hospital lifecycle history
  (who verified, rejected, suspended, reinstated, when, why) is lost** and cannot be rebuilt.
  Export it first if it matters.
- **Older application code does not know `REJECTED` or `SUSPENDED`.** The values live in
  `hospitals.verification_status` (VARCHAR, no CHECK constraint), so the downgrade does not
  touch them; pre-ADR-034 code reading such a row fails to map it to its enum. Before
  deploying older code, decide each such hospital's state explicitly (e.g. a reviewed data
  migration) — never by hand on a live database.
- Never point any of this at the development database on port 5433 from a test or script.

## Explicitly Deferred

Database-level append-only enforcement (M7); embeddings/pgvector (ADR-029); family-account linkage (Phase 2);
partitioning/archival (out of scope at this data volume — noted in the paper as future work).
