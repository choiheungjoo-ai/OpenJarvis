"""TTS ABC + ``TTSResult`` dataclass + ``save_wav`` helper.

Lives in its own module so concrete engines can import each other (or
not) without circular imports through ``__init__``.
"""

from __future__ import annotations

import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True, slots=True)
class TTSResult:
    """One synthesized utterance.

    ``audio`` is mono float32 in roughly [-1, 1]; ``sample_rate`` is
    whatever the engine produced (the router / file-writer resamples
    or saves accordingly).
    """

    audio: np.ndarray
    sample_rate: int

    @property
    def duration_seconds(self) -> float:
        return float(len(self.audio) / self.sample_rate) if self.sample_rate else 0.0


class TTS(ABC):
    """One TTS engine."""

    #: Stable identifier — used by the router, the fallback log, and
    #: tests. Must match the value persisted in
    #: ``tts_fallback_log.primary_engine`` etc. (step 5.13).
    name: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if getattr(cls, "__abstractmethods__", None):
            return
        if not getattr(cls, "name", None):
            raise TypeError(f"{cls.__name__}: TTS subclass must define 'name'")

    @abstractmethod
    def synthesize(
        self,
        text: str,
        *,
        language: str | None = None,
        voice_reference: Path | str | None = None,
        ref_text: str | None = None,
    ) -> TTSResult:
        """Synthesize ``text``; return audio.

        ``voice_reference`` is the path to a sample WAV for cloning
        engines (Qwen3-TTS, Chatterbox). ``ref_text`` is the exact
        transcript of that clip — Qwen3-TTS's ``generate_voice_clone``
        requires it. Engines that don't clone (or don't need a
        transcript) may ignore either.
        """


def save_wav(result: TTSResult, path: Path | str) -> None:
    """Write a TTSResult to a 16-bit mono PCM WAV file."""
    path = Path(path)
    pcm = (result.audio.clip(-1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(result.sample_rate)
        wf.writeframes(pcm.tobytes())


__all__ = ["TTS", "TTSResult", "save_wav"]
