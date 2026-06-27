"""Newton TTS service — FastAPI wrapper around qwen-tts.

Loads the JARVIS fine-tuned model and the Base clone model ONCE at startup
(GPU-resident — warm load is what makes synthesis fast). Exposes:

    GET  /health      -> 200 when both models are loaded
    POST /synthesize  -> { audio_b64, sample_rate }

The Newton core never imports torch/qwen-tts; it calls this over HTTP. The
request body maps 1:1 onto the verified two-mode adapter API:
  * custom_voice  -> generate_custom_voice(text, speaker, language)
  * clone         -> generate_voice_clone(text, language, ref_audio, ref_text)

Language MUST arrive as a full name ("korean"/"english") — the ko/en mapping
lives on the Newton side (qwen3.py:_to_full_language).
"""

from __future__ import annotations

import base64
import io
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from typing import Any, Literal

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("newton-tts")
logging.basicConfig(level=logging.INFO)

JARVIS_MODEL_DIR = os.environ.get(
    "JARVIS_MODEL_DIR", "/models/qwen3-tts-jarvis/v1-31samples-10ep"
)
BASE_MODEL_DIR = os.environ.get(
    "BASE_MODEL_DIR", "/models/qwen3-tts/Qwen3-TTS-12Hz-1.7B-Base"
)

_MODELS: dict[str, Any] = {}  # "jarvis" -> fine-tuned model, "base" -> clone model


def _load_models() -> None:
    """Import qwen-tts and load both models. Called once at startup."""
    import torch  # lazy: only inside the container
    from qwen_tts import Qwen3TTSModel  # lazy: only inside the container

    device = os.environ.get("TTS_DEVICE", "cuda:0")

    def _load_on_device(path: str):
        # Qwen3TTSModel.from_pretrained() lands on CPU and exposes no .to() /
        # .cuda() of its own; the heavy nn.Module is the inner .model. Move
        # that to the GPU and sync the wrapper's .device flag so generate()
        # runs on CUDA. Without this the model infers on CPU (~7s vs ~2s).
        model = Qwen3TTSModel.from_pretrained(path)
        if torch.cuda.is_available() and hasattr(model, "model"):
            model.model = model.model.to(device)
            try:
                model.device = torch.device(device)
            except Exception:  # noqa: BLE001 — best-effort flag sync
                pass
        log.info("  loaded on device: %s", getattr(model, "device", "unknown"))
        return model

    log.info("loading JARVIS fine-tuned model from %s", JARVIS_MODEL_DIR)
    _MODELS["jarvis"] = _load_on_device(JARVIS_MODEL_DIR)
    log.info("loading Base clone model from %s", BASE_MODEL_DIR)
    _MODELS["base"] = _load_on_device(BASE_MODEL_DIR)
    log.info("both models loaded")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN201, ARG001
    _load_models()
    yield
    _MODELS.clear()


app = FastAPI(title="Newton TTS", lifespan=lifespan)


class SynthesizeRequest(BaseModel):
    text: str = Field(min_length=1)
    language: Literal["korean", "english"]
    mode: Literal["custom_voice", "clone"]
    speaker: str | None = None  # custom_voice
    ref_audio_b64: str | None = None  # clone (base64 wav bytes)
    ref_text: str | None = None  # clone


class SynthesizeResponse(BaseModel):
    audio_b64: str
    sample_rate: int


@app.get("/health")
async def health() -> dict[str, bool]:
    ok = "jarvis" in _MODELS and "base" in _MODELS
    if not ok:
        raise HTTPException(status_code=503, detail="models not loaded")
    return {"ok": True}


def _wav_b64(audio: np.ndarray, sr: int) -> str:
    buf = io.BytesIO()
    sf.write(buf, np.asarray(audio, dtype=np.float32).reshape(-1), sr, format="WAV")
    return base64.b64encode(buf.getvalue()).decode("ascii")


@app.post("/synthesize", response_model=SynthesizeResponse)
async def synthesize(req: SynthesizeRequest) -> SynthesizeResponse:
    if req.mode == "custom_voice":
        if not req.speaker:
            raise HTTPException(422, "custom_voice requires 'speaker'")
        model = _MODELS["jarvis"]
        try:
            wavs, sr = model.generate_custom_voice(
                text=req.text, speaker=req.speaker, language=req.language
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"custom_voice failed: {e}") from e
    else:  # clone
        if not req.ref_audio_b64 or not req.ref_text:
            raise HTTPException(422, "clone requires 'ref_audio_b64' and 'ref_text'")
        # qwen-tts wants a path; write the ref wav to a temp file.
        ref_bytes = base64.b64decode(req.ref_audio_b64)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            tmp.write(ref_bytes)
            tmp.flush()
            model = _MODELS["base"]
            try:
                wavs, sr = model.generate_voice_clone(
                    text=req.text,
                    language=req.language,
                    ref_audio=tmp.name,
                    ref_text=req.ref_text,
                )
            except Exception as e:  # noqa: BLE001
                raise HTTPException(500, f"clone failed: {e}") from e

    audio = wavs[0] if isinstance(wavs, list) else wavs
    return SynthesizeResponse(audio_b64=_wav_b64(audio, sr), sample_rate=int(sr))
