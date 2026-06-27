#!/usr/bin/env bash
# Stop and remove the Newton TTS service container.
set -euo pipefail
cd "$(dirname "$0")/../.."
docker compose stop tts
docker compose rm -f tts
echo "newton-tts stopped."
