# Newton TTS service image.
#
# Bakes the hand-verified sm_120 stack: torch+torchaudio cu128, qwen-tts,
# FastAPI. Model weights are NOT baked — they mount at /models (see compose).
#
# Verified on this host (2026-06-27): inside this base image,
#   torch.cuda.is_available() == True, device RTX 5090, capability (12, 0).

FROM nvidia/cuda:12.8.0-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

# Python + ffmpeg (qwen-tts/soundfile lean on libsndfile; ffmpeg is handy).
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends \
        python3 python3-pip python3-venv \
        libsndfile1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# torch + torchaudio from the cu128 index FIRST, pinned to the verified
# build, so the qwen-tts install can't drag in a mismatched torchaudio
# (the _torchaudio.abi3.so trap we hit on the host).
RUN pip install --break-system-packages \
        --index-url https://download.pytorch.org/whl/cu128 \
        "torch==2.11.0+cu128" "torchaudio==2.11.0+cu128"

# qwen-tts + the server deps. qwen-tts pins transformers 4.57.3; that's fine
# here because this image is isolated from the Newton core's vllm/mlx pins.
RUN pip install --break-system-packages \
        qwen-tts \
        fastapi "uvicorn[standard]" soundfile numpy

# App.
WORKDIR /app
COPY server.py /app/server.py

# Model dirs are provided by the container environment (mounted /models).
ENV JARVIS_MODEL_DIR=/models/qwen3-tts-jarvis/v1-31samples-10ep \
    BASE_MODEL_DIR=/models/qwen3-tts/Qwen3-TTS-12Hz-1.7B-Base \
    TTS_DEVICE=cuda:0

EXPOSE 80

# Single worker: the models are big and GPU-resident; one process owns the GPU.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "80", "--workers", "1"]
