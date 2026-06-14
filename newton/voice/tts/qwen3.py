"""Qwen3-TTS CustomVoice adapter (lazy-loaded).

Two sizes ship in the design: 0.6B (Butler) and 1.7B (JARVIS-ko /
Friday). One adapter class, model size chosen at construction.

Loading
-------
The ``qwen-tts`` library is not imported at module-import time. The
first :meth:`synthesize` triggers ``_ensure_loaded``, which in turn
calls a ``loader`` callable. The default loader does the real import
+ ``from_pretrained``; tests inject a fake loader so they never need
the package or the model files.

Model files
-----------
Run ``scripts/newton/download-models.sh`` once to fetch both checkpoints
(~5 GB total). Place under ``$NEWTON_DATA_DIR/models/qwen3-tts/<size>/``.
The adapter resolves the path from config / env; missing files raise
at first synthesize, never at module load.

Voice reference
---------------
Cloning needs a WAV of the target voice. The router (step 5.5) maps
persona + language → reference path; the adapter just passes the path
through to the underlying model's ``ref_audio`` parameter.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

import numpy as np

from newton.voice.tts.base import TTS, TTSResult

log = logging.getLogger(__name__)


def _default_loader(model_size: str, model_root: Path) -> Any:
    """Real loader — imports qwen-tts and constructs the model.

    Wrapped in a helper so tests can substitute without monkeypatching
    the import system. The interface assumed here is conservative:
    ``from qwen_tts import Qwen3TTS; model = Qwen3TTS.from_pretrained(path)``.
    If the actual qwen-tts API differs once it lands, this is the one
    function that needs updating — the rest of the adapter doesn't care.
    """
    # Check the path first — a clearer error than an ImportError when
    # both the package and the weights are missing.
    target = model_root / model_size
    if not target.exists():
        raise FileNotFoundError(
            f"Qwen3-TTS {model_size} weights not found at {target}. "
            f"Run scripts/newton/download-models.sh first."
        )
    # Lazy import after the path check.
    from qwen_tts import Qwen3TTS as _Model  # noqa: PLC0415

    return _Model.from_pretrained(str(target))


class Qwen3TTS(TTS):
    """Qwen3-TTS engine wrapper."""

    name = "qwen3_tts"

    def __init__(
        self,
        model_size: str = "0.6B",
        sample_rate: int = 24000,
        model_root: Path | None = None,
        loader: Callable[[str, Path], Any] = _default_loader,
    ) -> None:
        if model_size not in {"0.6B", "1.7B"}:
            raise ValueError(f"model_size must be '0.6B' or '1.7B', got {model_size!r}")
        self.model_size = model_size
        self.sample_rate = sample_rate
        self._model: Any = None
        self._loader = loader
        self._model_root = model_root or _resolve_model_root()
        # The fallback log (4.13) wants the size in the engine identity.
        self.name = f"qwen3_tts_{model_size.lower()}"

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        log.info("loading Qwen3-TTS %s", self.model_size)
        self._model = self._loader(self.model_size, self._model_root)

    def synthesize(
        self,
        text: str,
        *,
        language: str | None = None,
        voice_reference: Path | str | None = None,
    ) -> TTSResult:
        if not text.strip():
            raise ValueError("text must be non-empty")
        self._ensure_loaded()

        # The underlying API is duck-typed via `.generate`; we honour
        # whatever shape it returns. Adapt one of the typical shapes:
        # numpy array, dict {"audio": ..., "sample_rate": ...}, or
        # tuple (audio, sample_rate).
        out = self._model.generate(
            text=text,
            ref_audio=str(voice_reference) if voice_reference else None,
            language=language,
        )
        audio, sr = _normalize_output(out, self.sample_rate)
        return TTSResult(audio=audio, sample_rate=sr)


def _normalize_output(out: Any, default_sr: int) -> tuple[np.ndarray, int]:
    """Coerce a model's audio output into (mono float32, sample_rate)."""
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
    """Where do Qwen3-TTS weights live? ``$NEWTON_DATA_DIR/models/qwen3-tts``."""
    env = os.environ.get("NEWTON_DATA_DIR")
    base = (
        Path(env).expanduser().resolve()
        if env
        else (Path(__file__).resolve().parent.parent.parent.parent / "data")
    )
    return base / "models" / "qwen3-tts"


__all__ = ["Qwen3TTS"]
