# scripts/

Operational scripts (owned here, run from repo root):

- **`export_openapi.py`** — writes the backend's OpenAPI spec to
  `web/packages/api-client/openapi.json` (run with `backend/.venv/bin/python`).
- **`generate-api-client.sh`** — full regeneration: export spec → generate
  `web/packages/api-client/src/generated/schema.ts` (openapi-typescript). Also available
  as `make api-client`. Generated output is machine-owned — never hand-edit; review the
  `openapi.json` diff in PRs (unintended spec drift = wrong PR).
- **`seed.py`** — idempotent reference-data seed: the 3 simulated hospitals
  (HID-0001..0003) + the record-category vocabulary. Safe to run any number of times;
  never duplicates or mutates existing rows. Requires a migrated DB
  (`alembic upgrade head`); run with `backend/.venv/bin/python scripts/seed.py`.
  Synthetic patients/doctors join it at M2.
- chain reconciliation job (M6, planned): verify DB audit log against on-chain anchors

`review1_deck/` is presentation tooling (regenerates `PulseOS_Review1.pptx` via
`python3 build.py`), not part of the product.
