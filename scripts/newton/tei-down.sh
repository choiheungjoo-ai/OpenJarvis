#!/usr/bin/env bash
# Newton v4 — stop the TEI service. Cached model weights are preserved.
#
# Usage:
#   scripts/newton/tei-down.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${PROJECT_ROOT}"

echo "→ docker compose stop tei"
docker compose stop tei
echo "✓ TEI stopped (model cache under data/tei/ preserved)"
