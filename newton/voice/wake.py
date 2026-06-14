"""Wake-word detection — openWakeWord wrapper + ABC.

The ABC keeps the Stage-1 detector agnostic of the underlying engine.
:class:`OpenWakeWordDetector` is the production class; it lazy-loads
the model on first :meth:`detect_chunk` so the core stays importable
without ``openwakeword`` installed.

Wake words shipped (per block-5 design):

    * ``newton`` — system wake
    * ``jarvis`` — also routes to persona=jarvis via block-3 engine
    * ``friday`` — also routes to persona=friday
    * ``butler`` — also routes to persona=butler

The engine's "matched name → persona" routing isn't this module's job;
we just emit which wake word fired. The persona engine handles the
rest.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class WakeMatch:
    """A single wake-word detection event."""

    wake_word: str
    score: float


class WakeDetector(ABC):
    """How does this detector see a chunk of mic audio?"""

    sample_rate: int = 16000

    @abstractmethod
    def detect_chunk(self, chunk: np.ndarray) -> WakeMatch | None:
        """Return the matched wake word + score, or ``None`` for "no match"."""


class OpenWakeWordDetector(WakeDetector):
    """openWakeWord wrapper. Lazy model load on first :meth:`detect_chunk`.

    The detector keeps a streaming buffer per wake word. openWakeWord
    expects 80 ms chunks at 16 kHz (1280 samples). We re-buffer
    arbitrary chunk sizes to match.

    Bring your own models: openwakeword ships pretrained ``jarvis``,
    ``alexa``, ``hey_jarvis`` etc. ``newton`` and other persona names
    need step 5.12 (custom training). For step 5.2 the detector is
    written so it handles whatever names are present — missing models
    just don't fire.
    """

    def __init__(
        self,
        wake_words: list[str],
        score_threshold: float = 0.5,
        sample_rate: int = 16000,
    ) -> None:
        self.wake_words = list(wake_words)
        self.score_threshold = score_threshold
        self.sample_rate = sample_rate
        self._model: Any = None
        self._buffer: np.ndarray | None = None
        # openWakeWord expects 1280-sample input frames at 16 kHz.
        self._frame_samples = int(sample_rate * 0.08)

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        from openwakeword.model import Model  # noqa: PLC0415 — lazy

        # ``wakeword_models`` is the kwarg openWakeWord uses; we pass
        # the user's names through directly. Anything missing falls
        # back to the library's pretrained set (the library validates).
        self._model = Model(wakeword_models=self.wake_words)

    def detect_chunk(self, chunk: np.ndarray) -> WakeMatch | None:
        self._ensure_loaded()
        # Accumulate until we have at least one openWakeWord frame.
        if self._buffer is None:
            self._buffer = chunk.astype(np.float32)
        else:
            self._buffer = np.concatenate([self._buffer, chunk.astype(np.float32)])

        if len(self._buffer) < self._frame_samples:
            return None

        # Run on one frame at a time; consume from the buffer.
        frame = self._buffer[: self._frame_samples]
        self._buffer = self._buffer[self._frame_samples :]
        # openWakeWord wants int16 PCM, not float; convert.
        pcm = (frame * 32767.0).clip(-32768, 32767).astype(np.int16)

        scores = self._model.predict(pcm)
        best_name: str | None = None
        best_score = 0.0
        for name, score in scores.items():
            if score >= self.score_threshold and score > best_score:
                best_name = name
                best_score = float(score)
        if best_name is None:
            return None
        return WakeMatch(wake_word=best_name, score=best_score)


# ─────────────────────────────────────────────────────────────────────────────
# Test stub — scripted matches, no model load
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ScriptedWakeDetector(WakeDetector):
    """Test fixture: emit a pre-scripted match on the N-th chunk fed.

    Useful for asserting Stage-1 routing without touching openwakeword.
    """

    scripted: dict[int, WakeMatch]
    sample_rate: int = 16000
    _counter: int = 0

    def detect_chunk(self, chunk: np.ndarray) -> WakeMatch | None:  # noqa: ARG002
        match = self.scripted.get(self._counter)
        self._counter += 1
        return match


__all__ = [
    "OpenWakeWordDetector",
    "ScriptedWakeDetector",
    "WakeDetector",
    "WakeMatch",
]
