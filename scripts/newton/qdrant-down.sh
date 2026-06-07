#!/usr/bin/env bash
# Newton v4 — stop the Qdrant service. Data on disk is preserved.
#
# Usage:
#   scripts/newton/qdrant-down.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${PROJECT_ROOT}"

echo "→ docker compose stop qdrant"
docker compose stop qdrant
echo "✓ qdrant stopped (data under data/qdrant/ preserved)"
