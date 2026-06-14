"""Tests for newton.voice.clap_detector — energy-peak 2-clap rule."""

from __future__ import annotations

import numpy as np
import pytest

from newton.voice.clap_detector import ClapDetector, ClapMatch
from newton.voice.config import ClapConfig

# At 16 kHz with 512-sample chunks, each chunk ≈ 32 ms.
# Default config: min_gap=90 ms (~3 chunks), max_gap=500 ms (~16 chunks).
CFG = ClapConfig(
    enabled=True,
    peak_threshold=0.15,
    min_gap_ms=90,
    max_gap_ms=500,
)


def _silent() -> np.ndarray:
    return np.zeros(512, dtype=np.float32)


def _peak(amp: float = 0.3) -> np.ndarray:
    return np.full(512, amp, dtype=np.float32)


def _detector() -> ClapDetector:
    return ClapDetector(config=CFG, sample_rate=16000, chunk_samples=512)


# ── basic firing ──────────────────────────────────────────────────────────


def test_two_peaks_in_window_fire():
    d = _detector()
    # First peak at chunk 0; back to silence; second peak at chunk 5
    # (5 × 32ms = 160 ms — between min 90 and max 500).
    sequence = [_peak()] + [_silent()] * 4 + [_peak()] + [_silent()] * 5
    events = []
    for c in sequence:
        m = d.detect_chunk(c)
        if m is not None:
            events.append(m)
    assert len(events) == 1
    assert isinstance(events[0], ClapMatch)
    # The second peak is at index 5 — that's what the match reports.
    assert events[0].chunk_index == 5


def test_single_peak_does_not_fire():
    d = _detector()
    sequence = [_peak()] + [_silent()] * 20
    events = [d.detect_chunk(c) for c in sequence]
    assert all(e is None for e in events)


# ── gap timing ────────────────────────────────────────────────────────────


def test_peaks_too_close_treated_as_one_event():
    """Two peaks within min_gap_ms = the second peak resets the anchor."""

    d = _detector()
    # First peak at chunk 0; silence; second peak at chunk 1 (32 ms < 90 ms).
    sequence = [_peak(), _peak()] + [_silent()] * 20
    events = []
    for c in sequence:
        m = d.detect_chunk(c)
        if m is not None:
            events.append(m)
    assert events == []


def test_peaks_too_far_apart_each_become_new_anchor():
    """A second peak past max_gap_ms restarts the pair-search."""

    d = _detector()
    # Peak at 0; long silence; peak at chunk 20 (640 ms > max 500).
    sequence = [_peak()] + [_silent()] * 19 + [_peak()] + [_silent()] * 5
    events = []
    for c in sequence:
        m = d.detect_chunk(c)
        if m is not None:
            events.append(m)
    assert events == []


def test_third_peak_after_pair_does_not_fire():
    """After firing, the anchor resets — a quick third peak isn't a re-fire."""

    d = _detector()
    # Pair at 0 and 5 fires. Then a peak at chunk 8 — no anchor → just
    # becomes new anchor, doesn't fire.
    sequence = [_peak()] + [_silent()] * 4 + [_peak()] + [_silent()] * 2 + [_peak()]
    matches = [d.detect_chunk(c) for c in sequence]
    fired = [m for m in matches if m is not None]
    assert len(fired) == 1
    assert fired[0].chunk_index == 5


# ── peak detection (edge transitions) ────────────────────────────────────


def test_peak_requires_below_to_above_transition():
    """A long stretch above threshold is one peak (the transition), not many."""

    d = _detector()
    # Peak at chunk 0, 1, 2 (all above) — only chunk 0 is a "peak"
    # because chunks 1 and 2 don't see a below→above transition.
    sequence = [_peak()] * 3 + [_silent()] * 4 + [_peak()] + [_silent()] * 5
    events = []
    for c in sequence:
        m = d.detect_chunk(c)
        if m is not None:
            events.append(m)
    # The second peak (at index 7) closes the pair with the first (at 0).
    # 7 × 32 = 224 ms — within window.
    assert len(events) == 1
    assert events[0].chunk_index == 7


def test_below_threshold_never_triggers():
    d = _detector()
    sequence = [np.full(512, CFG.peak_threshold - 0.01, dtype=np.float32)] * 20
    events = [d.detect_chunk(c) for c in sequence]
    assert all(e is None for e in events)


# ── disable switch ──────────────────────────────────────────────────────


def test_disabled_detector_emits_nothing():
    cfg_off = ClapConfig(
        enabled=False, peak_threshold=0.15, min_gap_ms=90, max_gap_ms=500
    )
    d = ClapDetector(config=cfg_off, sample_rate=16000, chunk_samples=512)
    sequence = [_peak()] + [_silent()] * 4 + [_peak()] + [_silent()] * 5
    events = [d.detect_chunk(c) for c in sequence]
    assert all(e is None for e in events)


# ── reset ───────────────────────────────────────────────────────────────


def test_reset_clears_state():
    d = _detector()
    d.detect_chunk(_peak())
    d.detect_chunk(_silent())
    d.reset()
    # After reset, a single peak is just the new first anchor.
    assert d.detect_chunk(_peak()) is None
    assert d._counter == 1  # noqa: SLF001


# ── rms_history exposed for test convenience ─────────────────────────────


def test_rms_history_tracks_chunks():
    d = _detector()
    d.detect_chunk(_silent())
    d.detect_chunk(_peak())
    assert len(d.rms_history) == 2
    assert d.rms_history[0] == pytest.approx(0.0)
    assert d.rms_history[1] == pytest.approx(0.3)
