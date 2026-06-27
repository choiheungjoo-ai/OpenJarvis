#!/usr/bin/env bash
# Bring up the Newton TTS service (JARVIS fine-tuned + Base clone over HTTP).
# Mirrors tei-up.sh. First run builds the image and loads two ~4GB models;
# /health goes 200 once both are resident (allow ~3 min).
set -euo pipefail
cd "$(dirname "$0")/../.."
docker compose up -d --build tts
echo "newton-tts starting on :${TTS_PORT:-8081} — first load takes a few minutes."
echo "watch:  docker logs -f newton-tts"
echo "ready:  curl -s http://localhost:${TTS_PORT:-8081}/health"
