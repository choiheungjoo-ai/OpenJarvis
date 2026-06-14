# Zero-shot cloning verification (block 5 step 5.5)

The router + adapters are scaffolded. The TTS models themselves load
lazily — Newton runs without them installed. This doc is what sir
follows to actually hear the clone.

## Pre-flight

```bash
# 1) Block 5 code shipped + green tests
git log --oneline | head -5      # should include 5.5 commit
uv run pytest tests/newton/voice/ -q

# 2) JARVIS donor samples present (step 5.4)
uv run newton voice samples show jarvis
# → 15 en samples, 16 ko samples, consent record green
```

## Install model packages

The voice extras aren't pre-pinned in pyproject because they're large
and infrequent. Install on demand:

```bash
# Qwen3-TTS 1.7B (JARVIS-ko + Friday)
uv add qwen-tts

# Chatterbox (JARVIS-en)
uv add chatterbox-tts
```

## Fetch the weights

```bash
# Default location: $NEWTON_DATA_DIR/models/<engine>/...
mkdir -p data/models/qwen3-tts data/models/chatterbox

# Qwen3-TTS 1.7B
huggingface-cli download Qwen/Qwen3-TTS-1.7B --local-dir data/models/qwen3-tts/1.7B

# Chatterbox
huggingface-cli download resemble-ai/chatterbox --local-dir data/models/chatterbox
```

If the HF repo names change, the adapter's loader call site is the
single update point (`newton/voice/tts/qwen3.py::_default_loader`
and the equivalent in `chatterbox.py`).

## Run the clone

```bash
# Korean — uses Qwen3-TTS 1.7B + jarvis/samples/ko/ko-001.wav
uv run newton voice tts --persona jarvis --lang ko \
    --text "안녕하십니까, sir."

# English — uses Chatterbox + jarvis/samples/en/en-001.wav
uv run newton voice tts --persona jarvis --lang en \
    --text "Right away, sir."
```

The CLI prints:

```
engine: qwen3_tts_1.7b
sample: data/voices/jarvis/samples/ko/ko-001.wav
output: /tmp/newton-voice-<timestamp>.wav  (1.4s)
```

Play it back through whatever audio path WSL is bridging to Windows.

## When the verification fails

| Symptom | Where to look |
|---------|---------------|
| `error: no TTS route for persona=... language=...` | `config/voice.yaml` — add or fix a `tts.routes` entry. |
| `error: voice sample ... not found` | check `data/voices/<persona>/samples/<lang>/`. The CLI fails before any model loads — fix the path before re-running. |
| `ModuleNotFoundError: qwen_tts` (or chatterbox) | run `uv add qwen-tts` / `uv add chatterbox-tts`. |
| `FileNotFoundError: ... weights not found at ...` | download the weights as above. |
| Audio plays but the tone is off | re-record the reference sample with a steadier delivery; single-reference clone is the v1 posture and quality scales with sample cleanness. |

## What's *not* this step's job

- Real-time turn-taking, session lock, voice approval — those are
  steps 5.10 and 5.13; verified separately.
- TTS fallback chain — wired in step 5.13; engages only when the
  primary engine fails one of the documented triggers.
- Multi-sample averaging — out of scope for v1.
- Friday / Butler clone verification — requires their donor recordings
  (step 5.4 hasn't shipped those yet).
