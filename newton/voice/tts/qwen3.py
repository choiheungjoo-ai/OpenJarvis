"""Qwen3-TTS adapter (lazy-loaded).

One adapter, two synthesis modes — both verified against the real
``qwen-tts`` API in ``docs/newton/jarvis-tts-training-verified.md``:

* **Custom voice** (fine-tuned speaker baked into the model — JARVIS):
  ``generate_custom_voice(text, speaker, language)``. No reference clip.
  Instance is constructed with ``speaker=...`` and the fine-tuned model
  path; ``synthesize`` ignores ``voice_reference`` / ``ref_text``.

* **Voice clone** (any persona with a clean reference clip):
  ``generate_voice_clone(text, language, ref_audio, ref_text)``.
  Instance is constructed without a speaker and points at the Base
  model; ``synthesize`` requires both ``voice_reference`` and
  ``ref_text`` (the clip's exact transcript).

Loading
-------
The ``qwen-tts`` library is not imported at module-import time. The
first :meth:`synthesize` call triggers ``_ensure_loaded``, which calls
the injected ``loader`` callable. The default loader does the real
import + ``Qwen3TTSModel.from_pretrained``; tests inject a fake loader
so they never need the package or the model files (Strategy D).

Language
--------
The router / config layer speaks ``"ko"`` / ``"en"``. The Qwen3-TTS
API takes full-name languages (``"korean"`` / ``"english"``). The
mapping lives in :func:`_to_full_language` — translate at the adapter
boundary, don't rip up the router's vocabulary.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

import numpy as np

from newton.voice.tts.base import TTS, TTSResult

log = logging.getLogger(__name__)


#: Default location of the Base cloning model under ``$NEWTON_DATA_DIR``.
DEFAULT_BASE_MODEL_DIR = Path("models/qwen3-tts/Qwen3-TTS-12Hz-1.7B-Base")
#: Default location of the JARVIS fine-tuned model under ``$NEWTON_DATA_DIR``.
DEFAULT_JARVIS_MODEL_DIR = Path("models/qwen3-tts-jarvis/v1-31samples-10ep")

#: Router/config language code → Qwen3-TTS full-name language.
_LANGUAGE_FULL_NAMES = {"ko": "korean", "en": "english"}


def _to_full_language(language: str | None) -> str | None:
    """Translate ``"ko"``/``"en"`` to ``"korean"``/``"english"``.

    Qwen3-TTS rejects short codes (``Unsupported languages: ['ko']``).
    Pass-through for ``None`` and for full names already; reject
    anything else loudly rather than letting the model error mid-call.
    """
    if language is None:
        return None
    if language in _LANGUAGE_FULL_NAMES:
        return _LANGUAGE_FULL_NAMES[language]
    if language in _LANGUAGE_FULL_NAMES.values():
        return language
    raise ValueError(
        f"unsupported Qwen3-TTS language {language!r}; "
        f"expected one of {sorted(_LANGUAGE_FULL_NAMES)} "
        f"or {sorted(_LANGUAGE_FULL_NAMES.values())}"
    )


def _default_loader(model_path: Path) -> Any:
    """Real loader — imports qwen-tts and constructs the model.

    Path-existence check runs first so a missing checkpoint produces a
    clearer error than the ImportError / HuggingFace 404 that
    ``Qwen3TTSModel.from_pretrained`` would otherwise raise.
    """
    if not model_path.exists():
        raise FileNotFoundError(
            f"Qwen3-TTS weights not found at {model_path}. "
            f"See docs/newton/jarvis-tts-training-verified.md."
        )
    from qwen_tts import Qwen3TTSModel  # noqa: PLC0415 — lazy import

    return Qwen3TTSModel.from_pretrained(str(model_path))


class Qwen3TTS(TTS):
    """Qwen3-TTS engine wrapper — clone OR custom-voice per instance."""

    name = "qwen3_tts"

    def __init__(
        self,
        *,
        name: str = "qwen3_tts",
        speaker: str | None = None,
        model_path: Path | None = None,
        sample_rate: int = 24000,
        loader: Callable[[Path], Any] = _default_loader,
    ) -> None:
        # Engine identity (used by the fallback log, the router cache key,
        # and the CLI's --json output). Distinct for clone vs custom-voice
        # so two instances coexist in the same router.
        self.name = name
        # ``speaker`` set → custom-voice mode (no reference needed).
        # ``speaker`` None → clone mode (caller must pass ref_audio + ref_text).
        self.speaker = speaker
        self.sample_rate = sample_rate
        self._model: Any = None
        self._loader = loader
        # Default to the Base cloning checkpoint when no path is supplied.
        # The custom-voice flavour ships its own path via the factory.
        self._model_path = model_path or _resolve_data_dir() / DEFAULT_BASE_MODEL_DIR

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        log.info("loading Qwen3-TTS from %s", self._model_path)
        self._model = self._loader(self._model_path)

    def synthesize(
        self,
        text: str,
        *,
        language: str | None = None,
        voice_reference: Path | str | None = None,
        ref_text: str | None = None,
    ) -> TTSResult:
        if not text.strip():
            raise ValueError("text must be non-empty")
        # Translate the router's short language code at the boundary so
        # the mapping rule lives in one place.
        full_language = _to_full_language(language)
        self._ensure_loaded()

        if self.speaker is not None:
            # Custom-voice mode: the speaker is baked into the fine-tuned
            # model. No reference clip / transcript is needed; if one was
            # passed it's silently ignored (the engine's mode is decided
            # at construction time).
            out = self._model.generate_custom_voice(
                text=text,
                speaker=self.speaker,
                language=full_language,
            )
        elif voice_reference is not None:
            # Clone mode: ref_text is REQUIRED by generate_voice_clone and
            # must match ref_audio exactly. A mismatched / missing
            # transcript yields garbled or wrong-length output, so fail
            # loud rather than letting the model do the wrong thing.
            if not ref_text or not ref_text.strip():
                raise ValueError(
                    "Qwen3-TTS clone mode needs ref_text matching voice_reference; "
                    f"got voice_reference={voice_reference!r} ref_text={ref_text!r}"
                )
            out = self._model.generate_voice_clone(
                text=text,
                language=full_language,
                ref_audio=str(voice_reference),
                ref_text=ref_text,
            )
        else:
            raise ValueError(
                "Qwen3TTS.synthesize requires either a configured speaker "
                "(custom-voice mode) or a voice_reference + ref_text pair "
                "(clone mode)"
            )

        audio, sr = _normalize_output(out, self.sample_rate)
        return TTSResult(audio=audio, sample_rate=sr)


def _normalize_output(out: Any, default_sr: int) -> tuple[np.ndarray, int]:
    """Coerce Qwen3-TTS output into ``(mono float32, sample_rate)``.

    The verified API returns ``(list[np.ndarray], sample_rate)`` and the
    caller takes ``wavs[0]``. Tests still cover the legacy shapes
    (dict, plain array, tuple of array+sr) so a future API tweak from
    upstream doesn't silently break us.
    """
    audio: Any
    sr: int
    if isinstance(out, tuple) and len(out) == 2:
        first, second = out
        if isinstance(first, list):
            if not first:
                raise ValueError("Qwen3-TTS returned an empty wav list")
            audio = first[0]
            sr = int(second)
        else:
            audio = first
            sr = int(second) if isinstance(second, (int, float)) else default_sr
    elif isinstance(out, list):
        if not out:
            raise ValueError("Qwen3-TTS returned an empty wav list")
        audio = out[0]
        sr = default_sr
    elif isinstance(out, dict):
        audio = out["audio"]
        if isinstance(audio, list):
            audio = audio[0]
        sr = int(out.get("sample_rate", default_sr))
    else:
        audio = out
        sr = default_sr

    arr = np.asarray(audio, dtype=np.float32)
    if arr.ndim > 1:
        arr = arr.mean(axis=-1) if arr.shape[-1] < arr.shape[0] else arr.mean(axis=0)
    return arr, int(sr)


def _resolve_data_dir() -> Path:
    """Where Newton's data tree lives — ``$NEWTON_DATA_DIR`` or repo default."""
    env = os.environ.get("NEWTON_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent.parent.parent.parent / "data"


def default_base_model_path() -> Path:
    """Path to the Base cloning model (clone mode default)."""
    return _resolve_data_dir() / DEFAULT_BASE_MODEL_DIR


def default_jarvis_model_path() -> Path:
    """Path to the JARVIS fine-tuned model (custom-voice mode default)."""
    return _resolve_data_dir() / DEFAULT_JARVIS_MODEL_DIR


__all__ = [
    "DEFAULT_BASE_MODEL_DIR",
    "DEFAULT_JARVIS_MODEL_DIR",
    "Qwen3TTS",
    "default_base_model_path",
    "default_jarvis_model_path",
]
