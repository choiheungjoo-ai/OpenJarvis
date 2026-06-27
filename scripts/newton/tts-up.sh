#!/usr/bin/env bash
# Bring up the Newton TTS service (JARVIS fine-tuned + Base clone over HTTP).
# Mirrors tei-up.sh, but the image build is EXPLICIT here (compose itself has
# build: commented + pull_policy:never, so `compose up tts` never rebuilds and
# can't hang after a Docker storage reset). First load brings two ~4GB models
# resident; /health goes 200 once both are loaded (allow ~3 min).
set -euo pipefail
cd "$(dirname "$0")/../.."

# Build only if the image is missing, or always when --build is passed.
if [[ "${1:-}" == "--build" ]] || ! docker image inspect newton-tts:dev >/dev/null 2>&1; then
  echo "building newton-tts:dev ..."
  docker compose build tts
fi

docker compose up -d tts
echo "newton-tts starting on :${TTS_PORT:-8081} — first load takes a few minutes."
echo "watch:  docker logs -f newton-tts"
echo "ready:  curl -s http://localhost:${TTS_PORT:-8081}/health"
