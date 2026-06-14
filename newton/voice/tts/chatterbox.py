"""Chatterbox TTS adapter for JARVIS-English (lazy-loaded).

Block-5 design pins JARVIS's English voice to Chatterbox for its
British-butler tone. The adapter mirrors the Qwen3TTS shape: lazy
``loader`` callable, output-shape coercion, no module-import-time
dependency on chatterbox-tts.

Watermark
---------
Chatterbox embeds a PerTh audio watermark in every output. Per sir's
decision noted in the block-5 design, the watermark is fine for
personal use.

Voice reference
---------------
A short (~5 s) British male voice clip lives at
``$NEWTON_DATA_DIR/voices/jarvis/chatterbox-reference.wav``. The
router resolves the path; the adapter just passes it through.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

import numpy as np

from newton.voice.tts.base import TTS, TTSResult

log = logging.getLogger(__name__)


def _default_loader(model_root: Path) -> Any:
    """Real loader — imports chatterbox-tts and constructs the model.

    The path-existence check runs first so missing weights produce a
    clearer error than an ImportError from chatterbox-tts.
    """
    if not model_root.exists():
        raise FileNotFoundError(
            f"Chatterbox weights not found at {model_root}. "
            f"Run scripts/newton/download-models.sh first."
        )
    from chatterbox.tts import ChatterboxTTS  # noqa: PLC0415 — lazy

    return ChatterboxTTS.from_pretrained(str(model_root))


class ChatterboxTTS(TTS):
    """Chatterbox engine wrapper."""

    name = "chatterbox"

    def __init__(
        self,
        sample_rate: int = 24000,
        model_root: Path | None = None,
        loader: Callable[[Path], Any] = _default_loader,
    ) -> None:
        self.sample_rate = sample_rate
        self._model: Any = None
        self._loader = loader
        self._model_root = model_root or _resolve_model_root()

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        log.info("loading Chatterbox TTS")
        self._model = self._loader(self._model_root)

    def synthesize(
        self,
        text: str,
        *,
        language: str | None = None,
        voice_reference: Path | str | None = None,
    ) -> TTSResult:
        if not text.strip():
            raise ValueError("text must be non-empty")
        # Chatterbox is English-tuned; the router only routes English
        # to it, but we don't enforce here — log if anything else
        # arrives so a misroute is visible.
        if language and language != "en":
            log.warning("Chatterbox got non-English language=%r", language)

        self._ensure_loaded()
        out = self._model.generate(
            text=text,
            audio_prompt_path=str(voice_reference) if voice_reference else None,
        )
        audio, sr = _normalize_output(out, self.sample_rate)
        return TTSResult(audio=audio, sample_rate=sr)


def _normalize_output(out: Any, default_sr: int) -> tuple[np.ndarray, int]:
    """Coerce Chatterbox output into ``(mono float32, sample_rate)``."""
    if isinstance(out, tuple) and len(out) == 2:
        audio, sr = out
    elif isinstance(out, dict):
        audio = out["audio"]
        sr = int(out.get("sample_rate", default_sr))
    else:
        audio = out
        sr = default_sr

    arr = np.asarray(audio, dtype=np.float32)
    if arr.ndim > 1:
        arr = arr.mean(axis=-1) if arr.shape[-1] < arr.shape[0] else arr.mean(axis=0)
    return arr, int(sr)


def _resolve_model_root() -> Path:
    env = os.environ.get("NEWTON_DATA_DIR")
    base = (
        Path(env).expanduser().resolve()
        if env
        else (Path(__file__).resolve().parent.parent.parent.parent / "data")
    )
    return base / "models" / "chatterbox"


__all__ = ["ChatterboxTTS"]
