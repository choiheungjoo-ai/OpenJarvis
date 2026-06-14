"""Stage-1 activation — clap OR wake word, both first-class.

The block-5 design holds two Stage-1 triggers equal:

    * a 2-clap pattern (config: ``stage1.clap``)
    * any wake word in ``stage1.wake.wake_words``

This module wraps both behind one ``feed(chunk)`` interface so the
rest of the voice stack doesn't case-split. ``Stage1Detector`` is
itself agnostic of which underlying engines are used — we pass in
the constructed ``WakeDetector`` and ``ClapDetector``. Tests inject
:class:`ScriptedWakeDetector` so they don't need openwakeword.

The detector reports an :class:`ActivationEvent` per chunk with the
kind (``"wake"`` / ``"clap"``) and, for wake events, the matched
word. The persona engine (block 3) maps a wake word to a persona.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from newton.voice.clap_detector import ClapDetector, ClapMatch
from newton.voice.wake import WakeDetector, WakeMatch


@dataclass(frozen=True, slots=True)
class ActivationEvent:
    """The result of one chunk going through Stage 1."""

    kind: str  # "wake" or "clap"
    chunk_index: int
    wake_word: str | None = None
    score: float | None = None

    @classmethod
    def from_wake(cls, chunk_index: int, match: WakeMatch) -> ActivationEvent:
        return cls(
            kind="wake",
            chunk_index=chunk_index,
            wake_word=match.wake_word,
            score=match.score,
        )

    @classmethod
    def from_clap(cls, chunk_index: int, match: ClapMatch) -> ActivationEvent:  # noqa: ARG003
        return cls(kind="clap", chunk_index=chunk_index)


@dataclass
class Stage1Detector:
    """Run both detectors against each chunk; emit the first hit.

    Wake wins ties (it's a more specific signal than a clap).
    Both detectors keep their own counters; passing the chunk index
    explicitly here gives ``ActivationEvent`` a consistent index.
    """

    wake: WakeDetector | None
    clap: ClapDetector | None
    _counter: int = 0

    def reset(self) -> None:
        self._counter = 0
        if self.clap is not None:
            self.clap.reset()

    def feed(self, chunk: np.ndarray) -> ActivationEvent | None:
        idx = self._counter
        self._counter += 1

        if self.wake is not None:
            match = self.wake.detect_chunk(chunk)
            if match is not None:
                return ActivationEvent.from_wake(idx, match)

        if self.clap is not None:
            cm = self.clap.detect_chunk(chunk)
            if cm is not None:
                return ActivationEvent.from_clap(idx, cm)

        return None


__all__ = ["ActivationEvent", "Stage1Detector"]
