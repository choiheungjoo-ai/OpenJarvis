#!/usr/bin/env bash
#
# Download Qwen3-TTS CustomVoice weights for the Newton voice stack.
#
# Block 5 step 5.3 introduces this script. Block 5 step 5.6 will add
# a Chatterbox reference clip; step 5.7 adds Whisper Large v3 weights.
# Each is opt-in — Newton runs without them, only the live voice
# loop needs them.
#
# Usage:
#   scripts/newton/download-models.sh           # both 0.6B + 1.7B
#   scripts/newton/download-models.sh 0.6B      # one size only
#
# Models land under $NEWTON_DATA_DIR/models/qwen3-tts/<size>/.
# Default NEWTON_DATA_DIR is <repo>/data.

set -euo pipefail

# Resolve target root.
data_dir="${NEWTON_DATA_DIR:-$(git rev-parse --show-toplevel)/data}"
target_root="$data_dir/models/qwen3-tts"
mkdir -p "$target_root"

# Sizes to fetch.
sizes=("$@")
if [ ${#sizes[@]} -eq 0 ]; then
    sizes=("0.6B" "1.7B")
fi

# The real Hugging Face repo path will land here once the user has a
# real Qwen3-TTS-CustomVoice host on their machine. Until then this
# script prints what it *would* do and exits non-zero so a CI run
# never accidentally fakes a successful download.
echo "would download Qwen3-TTS sizes: ${sizes[*]}"
echo "into: $target_root"
echo
echo "NOTE: the Hugging Face source for Qwen3-TTS-CustomVoice is not"
echo "      yet pinned in this script. Plug your repo path in here"
echo "      (e.g. via 'huggingface-cli download <repo> --local-dir <dest>')"
echo "      before relying on the model load path in newton.voice.tts.qwen3."
exit 1
