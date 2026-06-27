# Newton TTS Service — design (Strategy D, Docker)

Status: **design** (not yet built). Goal: serve JARVIS (fine-tuned) and clone
voices from a **separate GPU process**, so the Newton core stays torch-free —
exactly like the TEI embedding service. The in-repo adapter (`qwen3.py`,
verified API, committed `d4f5746`) becomes a thin HTTP client.

## Why a service (recap)
`qwen-tts` pulls a `transformers` pin that conflicts with vllm/mlx in the core
(`uv add qwen-tts` fails to resolve — proven). It must live outside the core
process. TEI already does this for embeddings; TTS follows the same shape.

## Architecture

```
Newton core (no torch)
  └─ newton/voice/tts/http_backend.py   ── HTTP ──▶  newton-tts container
       (httpx, async, errors wrapped)                 FastAPI + qwen-tts
                                                       JARVIS v1 + Base resident
                                                       RTX 5090 via CDI
```

The Newton process never imports torch/qwen-tts. All GPU work is in the
container. Mirrors `newton/vault/embedding_backends/tei.py` exactly.

## Components

### 1. Container image — `deploy/docker/tts/Dockerfile`
- Base: an image that already has CUDA 12.8 userspace for sm_120. Start from
  `nvidia/cuda:12.8.0-runtime-ubuntu24.04` (or PyTorch's cu128 image) and
  `pip install torch torchaudio --index-url .../cu128` + `qwen-tts` +
  `fastapi` + `uvicorn` + `soundfile`. (This bakes the painful
  torch/torchaudio/sm_120 combo we hand-verified today — that's the stability
  win.)
- Do NOT bake model weights into the image. Mount them (see compose).
- Exposes the FastAPI server on container port 80.

### 2. Server — `deploy/docker/tts/server.py` (FastAPI)
Loads models **once at startup** (resident — this is what makes it fast;
fine-tuning didn't speed inference, warm-load + streaming do). Holds:
- JARVIS fine-tuned model (`generate_custom_voice`, speaker="jarvis")
- Base model (`generate_voice_clone`) for clone personas

Endpoints (match what the in-repo adapter already expects):
```
GET  /health
    -> 200 when both models are loaded

POST /synthesize
    body: {
      "text": str,
      "language": "korean" | "english",   # full names (verified)
      "mode": "custom_voice" | "clone",
      "speaker": "jarvis" | null,          # custom_voice
      "ref_audio_b64": str | null,         # clone (base64 wav)
      "ref_text": str | null               # clone (required for clone)
    }
    -> { "audio_b64": str, "sample_rate": int }    # wav bytes, base64
```
Notes:
- Validate: clone mode requires ref_audio + ref_text; custom_voice requires
  speaker. Mirror the adapter's own checks so errors are consistent.
- Keep language as full names end-to-end; the *Newton-side* `ko`/`en`→full
  mapping already lives in `qwen3.py:_to_full_language` and stays there. The
  service receives full names only.
- Return audio as base64 wav (simple, language-agnostic). Streaming can be a
  later `/synthesize/stream` once the basic path works.

### 3. Compose — extend `docker-compose.yml`
Add a `tts` service mirroring `tei`:
```yaml
  tts:
    build: ./deploy/docker/tts
    container_name: newton-tts
    restart: unless-stopped
    ports:
      - "${TTS_PORT:-8081}:80"        # 8080 is TEI; TTS on 8081
    volumes:
      - ${TTS_MODEL_DIR:-./data/models}:/models:ro   # JARVIS v1 + Base, read-only
    environment:
      - JARVIS_MODEL_DIR=/models/qwen3-tts-jarvis/v1-31samples-10ep
      - BASE_MODEL_DIR=/models/qwen3-tts/Qwen3-TTS-12Hz-1.7B-Base
    healthcheck:
      test: ["CMD-SHELL", "bash -c ':> /dev/tcp/127.0.0.1/80' || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 180s     # first start loads two ~4GB models
    deploy:
      resources:
        reservations:
          devices:
            - driver: cdi
              capabilities: [gpu]
              device_ids:
                - nvidia.com/gpu=all
```

### 4. Scripts — `scripts/newton/tts-up.sh` / `tts-down.sh`
Mirror `tei-up.sh` / `tei-down.sh` (compose up -d tts / down).

### 5. Newton client — `newton/voice/tts/http_backend.py`
Mirror `tei.py`: an httpx async client wrapping the service. But it must plug
into the EXISTING `qwen3.py` adapter rather than duplicate it. Cleanest:
- Add a `loader`-level or backend-level option so `Qwen3TTS.synthesize`, when
  configured for "remote", calls the HTTP service instead of an in-process
  model. The adapter's two-mode logic (custom_voice vs clone) maps 1:1 onto
  the POST body, so the HTTP path can live behind the same `synthesize`
  signature.
- Wrap failures in the existing TTS error type; provide `health()`.
- Config: `tts.backend: remote | local`, `tts.url: http://localhost:8081`.

## Build & bring-up plan (staged — do NOT skip the GPU check)

1. **GPU-in-container check FIRST.** Before wiring anything, build a minimal
   image and confirm `torch.cuda.is_available()` is True AND the device is
   sm_120 inside the container. This is the one real unknown (host worked; the
   container CDI passthrough for Blackwell is unverified). If this fails, stop
   and fix the base image / CDI before building the rest.
2. Build the full image (torch cu128 + qwen-tts + fastapi).
3. Bring up `tts`; hit `/health`; then `/synthesize` with a JARVIS line; save
   the returned wav; copy to Windows; listen. Confirms parity with the v1 model
   we validated standalone.
4. Wire `http_backend.py` + config; `newton voice tts --persona jarvis` end to
   end through the service.
5. Later: `/synthesize/stream` for low-latency streaming.

## Constraints
- OpenJarvis: 0 lines. Newton core stays torch-free (verify
  `torch not in sys.modules` after importing the http backend).
- No hardcoding: ports, URLs, model dirs all via env/config.
- The verified adapter API (`d4f5746`) is the contract; the service conforms
  to it, not the other way round.
- Keep the existing `fake loader` test path so unit tests never need the
  service or torch.

## Open questions (decide during build)
- Base image: `nvidia/cuda:12.8-runtime` vs PyTorch official cu128 image —
  whichever gives a working sm_120 torch with the least image size.
- Streaming protocol (chunked HTTP vs websocket) — deferred to step 5.
- Whether Butler/Friday clone voices ship now or later (service supports clone
  from day one; personas can be added in config).
