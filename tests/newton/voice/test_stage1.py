"""Tests for newton.voice.stage1 — clap OR wake unified Stage 1."""

from __future__ import annotations

import numpy as np

from newton.voice.clap_detector import ClapDetector
from newton.voice.config import ClapConfig
from newton.voice.stage1 import ActivationEvent, Stage1Detector
from newton.voice.wake import ScriptedWakeDetector, WakeMatch


def _silent() -> np.ndarray:
    return np.zeros(512, dtype=np.float32)


def _peak() -> np.ndarray:
    return np.full(512, 0.3, dtype=np.float32)


# ── only wake configured ─────────────────────────────────────────────────


def test_stage1_emits_wake_event():
    wake = ScriptedWakeDetector(scripted={3: WakeMatch(wake_word="jarvis", score=0.85)})
    s1 = Stage1Detector(wake=wake, clap=None)
    events = []
    for _ in range(5):
        e = s1.feed(_silent())
        if e is not None:
            events.append(e)
    assert len(events) == 1
    assert events[0] == ActivationEvent(
        kind="wake", chunk_index=3, wake_word="jarvis", score=0.85
    )


# ── only clap configured ────────────────────────────────────────────────


def test_stage1_emits_clap_event():
    clap = ClapDetector(
        config=ClapConfig(
            enabled=True, peak_threshold=0.15, min_gap_ms=90, max_gap_ms=500
        ),
        sample_rate=16000,
        chunk_samples=512,
    )
    s1 = Stage1Detector(wake=None, clap=clap)

    sequence = [_peak()] + [_silent()] * 4 + [_peak()] + [_silent()] * 5
    events = []
    for c in sequence:
        e = s1.feed(c)
        if e is not None:
            events.append(e)
    assert len(events) == 1
    assert events[0].kind == "clap"
    # Stage1 tracks its own counter — clap fires when feeding chunk 5.
    assert events[0].chunk_index == 5


# ── both configured: wake wins tie ──────────────────────────────────────


def test_wake_wins_when_both_would_fire():
    """A chunk that would fire clap AND wake reports as wake (more specific)."""

    wake = ScriptedWakeDetector(scripted={0: WakeMatch(wake_word="newton", score=0.9)})
    clap = ClapDetector(
        config=ClapConfig(
            enabled=True, peak_threshold=0.15, min_gap_ms=90, max_gap_ms=500
        ),
        sample_rate=16000,
        chunk_samples=512,
    )
    # Pre-arm clap so the *next* peak would fire — then verify wake
    # takes precedence on chunk 0.
    clap.detect_chunk(_peak())  # anchor
    clap.detect_chunk(_silent())
    clap.detect_chunk(_silent())
    clap.detect_chunk(_silent())
    clap.detect_chunk(_silent())  # 5th chunk silence (160 ms in)

    s1 = Stage1Detector(wake=wake, clap=clap)
    e = s1.feed(_peak())  # this would close the clap pair AND fire wake
    assert e is not None
    assert e.kind == "wake"


# ── neither fires when nothing matches ──────────────────────────────────


def test_stage1_no_event_on_silence():
    wake = ScriptedWakeDetector(scripted={})
    clap = ClapDetector(
        config=ClapConfig(
            enabled=True, peak_threshold=0.15, min_gap_ms=90, max_gap_ms=500
        ),
        sample_rate=16000,
        chunk_samples=512,
    )
    s1 = Stage1Detector(wake=wake, clap=clap)
    for _ in range(20):
        assert s1.feed(_silent()) is None


# ── reset clears state on both ──────────────────────────────────────────


def test_stage1_reset_clears_clap_state():
    wake = ScriptedWakeDetector(scripted={})
    clap = ClapDetector(
        config=ClapConfig(
            enabled=True, peak_threshold=0.15, min_gap_ms=90, max_gap_ms=500
        ),
        sample_rate=16000,
        chunk_samples=512,
    )
    s1 = Stage1Detector(wake=wake, clap=clap)
    s1.feed(_peak())  # anchor armed
    s1.reset()
    # After reset, a single peak is just a new anchor — won't fire.
    sequence = [_silent()] * 5 + [_peak()] + [_silent()] * 5
    events = [s1.feed(c) for c in sequence]
    assert all(e is None for e in events)
