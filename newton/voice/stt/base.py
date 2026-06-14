"""STT ABC + ``Transcription`` dataclass.

Concrete engines live alongside this module (whisper.py, …) and may
import each other freely. The ABC is intentionally small: one
``transcribe`` method, a dataclass result, and a stable engine name
for telemetry.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True, slots=True)
class Transcription:
    """One STT result.

    ``text`` is the final transcript. ``language`` is what the engine
    auto-detected (or what the caller pinned). ``segments`` carries
    optional per-segment timing for surfaces that want it (meeting
    mode, action-item extraction); engines that don't produce segments
    leave it empty.
    """

    text: str
    language: str
    duration_seconds: float
    segments: list[dict] = field(default_factory=list)


class STT(ABC):
    """One STT engine."""

    #: Stable identifier — used for telemetry and the (later) STT
    #: corpus accumulation. Subclasses must define it at class level.
    name: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if getattr(cls, "__abstractmethods__", None):
            return
        if not getattr(cls, "name", None):
            raise TypeError(f"{cls.__name__}: STT subclass must define 'name'")

    @abstractmethod
    def transcribe(
        self,
        audio: np.ndarray,
        *,
        sample_rate: int = 16000,
        language: str | None = None,
        initial_prompt: str | None = None,
    ) -> Transcription:
        """Transcribe a mono float32 audio array.

        ``language`` pins the recognition language (e.g. ``"ko"`` or
        ``"en"``). ``None`` lets the engine auto-detect.
        ``initial_prompt`` is the contextual-biasing handle the
        block-5.8 BiasingDict feeds in.
        """


__all__ = ["STT", "Transcription"]
