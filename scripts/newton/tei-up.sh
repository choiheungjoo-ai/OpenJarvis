#!/usr/bin/env bash
# Newton v4 — start the TEI (text-embeddings-inference) service and wait
# until it answers /health.
#
# Usage:
#   scripts/newton/tei-up.sh
#
# First run downloads the model (~2GB) and can take a few minutes; the wait
# loop is patient. Idempotent on a healthy instance.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TEI_URL="${TEI_URL:-http://localhost:8080}"
WAIT_SECONDS="${TEI_WAIT_SECONDS:-600}"

cd "${PROJECT_ROOT}"

echo "→ docker compose up -d tei"
docker compose up -d tei

echo -n "→ waiting for ${TEI_URL}/health (up to ${WAIT_SECONDS}s; first run pulls model) "
for _ in $(seq 1 "${WAIT_SECONDS}"); do
    if curl -fsS "${TEI_URL}/health" >/dev/null 2>&1; then
        echo
        echo "✓ TEI is healthy at ${TEI_URL}"
        exit 0
    fi
    echo -n "."
    sleep 1
done

echo
echo "✗ TEI did not become healthy within ${WAIT_SECONDS}s" >&2
echo "  inspect with:  docker logs newton-tei" >&2
exit 1
