"""Whisper Large v3 via faster-whisper — lazy-loaded.

faster-whisper uses CTranslate2 (no PyTorch) so the dep weight is
materially lower than the TTS adapters. But weights still load on
first use — keep the lazy contract anyway so the core stays
importable on machines without the package or the model files.

Model files
-----------
``$NEWTON_DATA_DIR/models/whisper-large-v3/`` (faster-whisper's
local directory layout). The default loader checks the path before
importing so a missing-weights error is clearer than an ImportError.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from newton.voice.stt.base import STT, Transcription

log = logging.getLogger(__name__)


def _default_loader(model_root: Path, compute_type: str) -> Any:
    """Real loader — import faster_whisper and construct the model."""
    if not model_root.exists():
        raise FileNotFoundError(
            f"Whisper weights not found at {model_root}. "
            f"Run scripts/newton/download-models.sh first."
        )
    from faster_whisper import WhisperModel  # noqa: PLC0415 — lazy

    return WhisperModel(str(model_root), compute_type=compute_type)


class WhisperSTT(STT):
    """faster-whisper wrapper.

    Construction takes a ``compute_type`` (``int8`` / ``int8_float16`` /
    ``float16``) so sir can trade VRAM for quality without an upstream
    config change. Defaults to ``int8_float16``, matching tech-stack.
    """

    name = "whisper_large_v3"

    def __init__(
        self,
        compute_type: str = "int8_float16",
        model_root: Path | None = None,
        loader: Callable[[Path, str], Any] = _default_loader,
    ) -> None:
        self.compute_type = compute_type
        self._model: Any = None
        self._loader = loader
        self._model_root = model_root or _resolve_model_root()

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        log.info("loading Whisper Large v3 (compute_type=%s)", self.compute_type)
        self._model = self._loader(self._model_root, self.compute_type)

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        sample_rate: int = 16000,
        language: str | None = None,
        initial_prompt: str | None = None,
    ) -> Transcription:
        if audio.ndim != 1:
            raise ValueError(
                f"transcribe expects mono float32 audio, got shape={audio.shape}"
            )
        if sample_rate != 16000:
            # faster-whisper resamples internally, but the design
            # commits us to 16 kHz throughout the voice stack; surface
            # the mismatch rather than masking it.
            log.warning(
                "Whisper transcribe got sample_rate=%d, expected 16000",
                sample_rate,
            )

        self._ensure_loaded()

        segments_iter, info = self._model.transcribe(
            audio.astype(np.float32),
            language=language,
            initial_prompt=initial_prompt,
            beam_size=5,
            vad_filter=False,  # we already VAD upstream
        )
        segments = list(segments_iter)
        text = "".join(seg.text for seg in segments).strip()
        return Transcription(
            text=text,
            language=str(info.language),
            duration_seconds=float(info.duration),
            segments=[
                {
                    "start": float(s.start),
                    "end": float(s.end),
                    "text": s.text,
                }
                for s in segments
            ],
        )


def _resolve_model_root() -> Path:
    env = os.environ.get("NEWTON_DATA_DIR")
    base = (
        Path(env).expanduser().resolve()
        if env
        else (Path(__file__).resolve().parent.parent.parent.parent / "data")
    )
    return base / "models" / "whisper-large-v3"


__all__ = ["WhisperSTT"]
