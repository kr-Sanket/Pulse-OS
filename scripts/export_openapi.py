"""Export the backend's OpenAPI spec for api-client generation (ADR-003).

Run with the backend virtualenv's Python (it has the app installed editable):

    backend/.venv/bin/python scripts/export_openapi.py

The spec is the single source of truth for web/packages/api-client; the TypeScript
client is generated from it and never hand-edited (docs/API_GUIDELINES.md §Documentation).
Output is deterministic (sorted keys) so spec diffs in review show real API changes only.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "web" / "packages" / "api-client" / "openapi.json"


def main() -> int:
    from app.main import create_app

    spec = create_app().openapi()
    SPEC_PATH.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"OpenAPI spec written to {SPEC_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
