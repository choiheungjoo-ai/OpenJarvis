"""Voice Activity Detection — Silero VAD wrapper + ABC.

The ABC lets every downstream stage take "some VAD" without caring
which model is behind it. Tests inject a deterministic stub
(:class:`RmsVAD` is shipped for exactly that — see tests). Production
uses :class:`SileroVAD`, which lazy-loads the model on the first
:meth:`detect` call.

Streaming
---------
The doc-level "is this speech?" decision is per-chunk: each chunk
yields a probability. The :class:`SpeechSegmenter` on top of that
turns the chunk stream into discrete speech segments using the
``min_speech_chunks`` / ``min_silence_chunks`` thresholds from
``VADConfig``. Segmenter state is explicit (not global), so multiple
voice sessions can run independently.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from newton.voice.config import VADConfig


@dataclass(frozen=True, slots=True)
class VADResult:
    """One chunk's worth of speech / silence decision."""

    is_speech: bool
    probability: float


class VAD(ABC):
    """How does this VAD see one chunk?"""

    sample_rate: int = 16000
    threshold: float = 0.5

    @abstractmethod
    def detect(self, chunk: np.ndarray) -> VADResult:
        """Return whether ``chunk`` (mono float32) is speech."""


# ─────────────────────────────────────────────────────────────────────────────
# Production: Silero VAD (lazy-loaded)
# ─────────────────────────────────────────────────────────────────────────────


class SileroVAD(VAD):
    """Silero VAD wrapped with a lazy model load.

    The model + torch are NOT imported at module import. The first
    :meth:`detect` triggers ``from silero_vad import load_silero_vad``
    and ``import torch``. Tests that don't actually want a VAD use
    :class:`RmsVAD` (no torch dep).

    Silero expects 16 kHz mono float32, chunked at 512 samples.
    Passing other rates is a config error; the constructor accepts
    it for forward-compat but warns through the abstract attribute.
    """

    def __init__(
        self,
        threshold: float = 0.5,
        sample_rate: int = 16000,
    ) -> None:
        self.threshold = threshold
        self.sample_rate = sample_rate
        self._model: Any = None
        # Cached torch handle; populated alongside ``_model``.
        self._torch: Any = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        # Both imports are lazy. silero_vad transitively pulls torch;
        # we capture both module handles for the predict path so we
        # don't repeat the import cost on every chunk.
        import torch  # noqa: PLC0415 — lazy
        from silero_vad import load_silero_vad  # noqa: PLC0415 — lazy

        self._torch = torch
        self._model = load_silero_vad()

    def detect(self, chunk: np.ndarray) -> VADResult:
        self._ensure_loaded()
        tensor = self._torch.from_numpy(chunk.astype(np.float32))
        probability = float(self._model(tensor, self.sample_rate).item())
        return VADResult(
            is_speech=probability >= self.threshold,
            probability=probability,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Test / fallback: RMS-threshold VAD (no model, no torch)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class RmsVAD(VAD):
    """Decide "speech" by raw RMS amplitude.

    Useful for tests (no torch dep, deterministic) and as a safety
    fallback when Silero is unavailable. It's a *terrible* speech
    detector in absolute terms — a keyboard click crosses the
    threshold too — so production callers should always prefer
    :class:`SileroVAD`.
    """

    threshold: float = 0.02
    sample_rate: int = 16000

    def detect(self, chunk: np.ndarray) -> VADResult:
        rms = float(np.sqrt(np.mean(np.square(chunk.astype(np.float32)))))
        # Map RMS to a 0..1 "probability" so callers can rank chunks
        # by loudness — twice-threshold ⇒ 1.0; threshold ⇒ 0.5.
        prob = min(1.0, rms / (self.threshold * 2.0))
        return VADResult(
            is_speech=rms >= self.threshold,
            probability=prob,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Streaming segmenter — turns per-chunk decisions into speech segments
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class SegmentEvent:
    """A speech-segment boundary the segmenter reports to its caller."""

    kind: str  # "speech_start" | "speech_end"
    chunk_index: int  # which chunk emitted this transition


@dataclass
class SpeechSegmenter:
    """Turn a per-chunk speech/silence stream into discrete segments.

    Apply ``min_speech_chunks`` hysteresis on the way in (filters
    one-off blips) and ``min_silence_chunks`` on the way out (so
    natural pauses inside speech don't fragment a segment).

    The segmenter holds explicit state and is reusable across
    sessions via ``reset()``. ``feed(chunk_index, result)`` returns
    a list of events (usually empty — only transitions emit).
    """

    config: VADConfig
    _in_speech: bool = False
    _speech_run: int = 0
    _silence_run: int = 0
    _buffer_indices: list[int] = field(default_factory=list)

    def reset(self) -> None:
        self._in_speech = False
        self._speech_run = 0
        self._silence_run = 0
        self._buffer_indices.clear()

    def feed(self, chunk_index: int, result: VADResult) -> list[SegmentEvent]:
        events: list[SegmentEvent] = []
        if result.is_speech:
            self._speech_run += 1
            self._silence_run = 0
            if (
                not self._in_speech
                and self._speech_run >= self.config.min_speech_chunks
            ):
                self._in_speech = True
                events.append(SegmentEvent("speech_start", chunk_index))
        else:
            self._silence_run += 1
            self._speech_run = 0
            if self._in_speech and self._silence_run >= self.config.min_silence_chunks:
                self._in_speech = False
                events.append(SegmentEvent("speech_end", chunk_index))
        return events

    @property
    def in_speech(self) -> bool:
        return self._in_speech


__all__ = [
    "RmsVAD",
    "SegmentEvent",
    "SileroVAD",
    "SpeechSegmenter",
    "VAD",
    "VADResult",
]
