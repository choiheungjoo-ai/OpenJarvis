#!/usr/bin/env bash
# Newton v4 — start the Qdrant service and wait until it answers /healthz.
#
# Usage:
#   scripts/newton/qdrant-up.sh
#
# Idempotent: re-running on a healthy instance is a no-op.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"

cd "${PROJECT_ROOT}"

echo "→ docker compose up -d qdrant"
docker compose up -d qdrant

echo -n "→ waiting for ${QDRANT_URL}/healthz "
for _ in $(seq 1 30); do
    if curl -fsS "${QDRANT_URL}/healthz" >/dev/null 2>&1; then
        echo
        echo "✓ qdrant is healthy at ${QDRANT_URL}"
        exit 0
    fi
    echo -n "."
    sleep 1
done

echo
echo "✗ qdrant did not become healthy within 30s" >&2
echo "  inspect with:  docker logs newton-qdrant" >&2
exit 1
