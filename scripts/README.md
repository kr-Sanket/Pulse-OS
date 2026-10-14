# scripts/

Operational scripts (owned here, run from repo root):

- **`export_openapi.py`** — writes the backend's OpenAPI spec to
  `web/packages/api-client/openapi.json` (run with `backend/.venv/bin/python`).
- **`generate-api-client.sh`** — full regeneration: export spec → generate
  `web/packages/api-client/src/generated/schema.ts` (openapi-typescript). Also available
  as `make api-client`. Generated output is machine-owned — never hand-edit; review the
  `openapi.json` diff in PRs (unintended spec drift = wrong PR).
- **`dev_link_identity.py`** — **local development only.** Attaches a real Firebase UID to
  an existing *seeded* identity, so a Google account can sign in as e.g. the TMH demo
  hospital admin without hand-written SQL. Creates nothing (no user, hospital, admin,
  doctor or patient) and never chooses a role — the role comes from the row that already
  exists. Refuses to run unless `PULSEOS_ENVIRONMENT=local` **and** the database host is
  this machine; there is no `--force`, deliberately. Start with `--list`.

  ```bash
  backend/.venv/bin/python scripts/dev_link_identity.py --list
  backend/.venv/bin/python scripts/dev_link_identity.py \
      --user-email admin.tmh@demo.pulseos.test --firebase-uid <REAL_FIREBASE_UID>
  ```

  It can also correct the PulseOS profile of an identity it has linked — **HOSPITAL_ADMIN
  only**, two fields, both explicit — because linking changes `firebase_uid` alone and
  leaves a real developer signing in behind a seeded demo name:

  ```bash
  backend/.venv/bin/python scripts/dev_link_identity.py \
      --firebase-uid <REAL_FIREBASE_UID> \
      --full-name "Your Name" --email you@example.com
  ```

  This is not a profile editor: `--full-name`/`--email` require `--firebase-uid`, the row
  must already be (or become, in the same run) that UID's identity, patient and doctor rows
  are refused, and an email already held by another `users` row is refused. Once the email
  has been corrected the seeded address no longer names the row — resolve it by
  `--firebase-uid` from then on. The Firebase account itself is never written to.

  **Caution before re-running `seed.py`.** While a seeded row carries a real UID the seed
  can no longer find it by its `synthetic:` subject, so it inserts a *second* user and a
  *second* hospital-admin row for the same hospital (`hospital_admins.hospital_id` is not
  unique). There is deliberately no unlink command yet — restoring the original subject is
  a destructive edit to a row a real account is signing in with, and needs its own slice.
- **`seed.py`** — idempotent development/demo seed: the 3 simulated hospitals
  (HID-0001..0003), the 13-code record-category vocabulary, one demo admin and one demo doctor
  per hospital, and 3 synthetic patients with pinned Health IDs. Safe to run any number of times;
  never duplicates or mutates existing rows. Requires a migrated DB
  (`cd backend && .venv/bin/alembic upgrade head`); run with
  `backend/.venv/bin/python scripts/seed.py`.
- **`import_synthea.py`** — imports pinned Synthea FHIR R4 patients as ordinary patients and
  records (proposed ADR-030; docs/DOMAIN_MODEL.md §6). Idempotent and non-destructive; writes no
  consent or audit rows; can index the imported resources into the AI tables. Logic lives in
  `records/fhir_mapping.py` and `records/fhir_import.py`; the script wires engine, session and
  one transaction per bundle. Reads bundles from `FHIR_Dataset/fhir/` by default (git-ignored —
  obtain the Synthea corpus locally).
- **`backfill_ai.py`** — indexes records already in object storage into the AI tables through
  the same ingestion path as the import. Non-destructive; FHIR records only (no OCR).
- **Audit reconciliation** is a library today (`AuditBatchService.reconcile`, ADR-027) with no
  CLI. The chain-side reconciliation job is planned and not authorized (M6.4+).

`review1_deck/` is presentation tooling (regenerates `PulseOS_Review1.pptx` via
`python3 build.py`), not part of the product.

