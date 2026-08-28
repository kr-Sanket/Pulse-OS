#!/usr/bin/env bash
# Regenerate web/packages/api-client from the backend's OpenAPI spec (ADR-003).
# Usage: scripts/generate-api-client.sh   (or `make api-client`)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$ROOT/backend/.venv/bin/python" "$ROOT/scripts/export_openapi.py"
cd "$ROOT/web"
pnpm --filter @pulseos/api-client generate
echo "api-client regenerated. Review the openapi.json diff: unintended spec drift = wrong PR."
