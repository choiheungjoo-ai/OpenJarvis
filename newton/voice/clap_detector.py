"""2-clap-in-sequence trigger — energy-based, no model.

The doc mentions an openWakeWord-trained clap classifier as the
end-state. For block 5.2 we ship a deterministic energy-peak
detector: two distinct peaks within a configurable window count as a
wake event. The pair-in-window rule rejects most false positives
(door slams, single hand-claps, TV applause) without an extra
trained model.

Algorithm
---------
Per chunk:

    rms = sqrt(mean(chunk²))

A chunk is a "peak" when:
    * rms >= peak_threshold
    * the previous chunk was below the threshold (transition)

Track the timestamp (chunk index → ms) of the most recent peak.
When a *second* peak appears with min_gap_ms ≤ Δt ≤ max_gap_ms,
emit a clap. After that, the most recent peak is reset — a 3rd
quick clap doesn't trigger a second event.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from newton.voice.config import ClapConfig


@dataclass(frozen=True, slots=True)
class ClapMatch:
    """Marker that a 2-clap pattern just fired."""

    chunk_index: int  # index of the second peak that closed the pair


@dataclass
class ClapDetector:
    """Stream of chunks → optional :class:`ClapMatch` per chunk.

    Construct once per Stage-1 session and call :meth:`detect_chunk`
    for each incoming audio chunk. State is explicit; :meth:`reset`
    is provided for re-use across sessions.
    """

    config: ClapConfig
    sample_rate: int = 16000
    chunk_samples: int = 512
    _counter: int = 0
    _prev_above: bool = False
    _last_peak_index: int | None = None
    # In tests we may want to spy on per-chunk RMS values; expose
    # the latest computation for assertion convenience.
    rms_history: list[float] = field(default_factory=list)

    @property
    def _chunk_duration_ms(self) -> float:
        return 1000.0 * self.chunk_samples / self.sample_rate

    def reset(self) -> None:
        self._counter = 0
        self._prev_above = False
        self._last_peak_index = None
        self.rms_history.clear()

    def detect_chunk(self, chunk: np.ndarray) -> ClapMatch | None:
        if not self.config.enabled:
            self._counter += 1
            return None

        rms = float(np.sqrt(np.mean(np.square(chunk.astype(np.float32)))))
        self.rms_history.append(rms)
        above = rms >= self.config.peak_threshold
        is_peak = above and not self._prev_above

        self._prev_above = above
        idx = self._counter
        self._counter += 1

        if not is_peak:
            return None

        if self._last_peak_index is None:
            self._last_peak_index = idx
            return None

        # Two peaks: check the gap.
        gap_ms = (idx - self._last_peak_index) * self._chunk_duration_ms
        if gap_ms < self.config.min_gap_ms:
            # Too close — treat both peaks as one event, advance the
            # window so the next genuine clap starts a fresh pair.
            self._last_peak_index = idx
            return None
        if gap_ms > self.config.max_gap_ms:
            # Too far — the first peak was a one-off; this becomes
            # the new pair anchor.
            self._last_peak_index = idx
            return None

        # In-window pair — fire.
        self._last_peak_index = None
        return ClapMatch(chunk_index=idx)


__all__ = ["ClapDetector", "ClapMatch"]
