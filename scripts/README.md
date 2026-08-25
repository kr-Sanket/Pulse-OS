# scripts/

Operational scripts (owned here, run from repo root):

- seed script (M2): 3 simulated hospitals + synthetic patients — idempotent
- OpenAPI client generation for web/packages/api-client (M0.3)
- chain reconciliation job (M6): verify DB audit log against on-chain anchors

No operational scripts exist yet. `review1_deck/` is presentation tooling (regenerates
`PulseOS_Review1.pptx` via `python3 build.py`), not part of the product.
