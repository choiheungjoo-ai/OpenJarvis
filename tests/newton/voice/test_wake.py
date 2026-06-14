"""Tests for newton.voice.wake — WakeDetector ABC + lazy load + Stage1."""

from __future__ import annotations

import sys

import numpy as np
import pytest

from newton.voice.wake import (
    OpenWakeWordDetector,
    ScriptedWakeDetector,
    WakeDetector,
    WakeMatch,
)


def _silent() -> np.ndarray:
    return np.zeros(512, dtype=np.float32)


def test_wake_detector_abc():
    with pytest.raises(TypeError):
        WakeDetector()  # type: ignore[abstract]


# ── ScriptedWakeDetector (the test workhorse) ────────────────────────────


def test_scripted_detector_emits_match_at_scheduled_chunk():
    d = ScriptedWakeDetector(scripted={2: WakeMatch(wake_word="jarvis", score=0.9)})
    out = [d.detect_chunk(_silent()) for _ in range(5)]
    assert out[0] is None
    assert out[1] is None
    assert out[2] == WakeMatch(wake_word="jarvis", score=0.9)
    assert out[3] is None


def test_scripted_detector_empty_script_never_fires():
    d = ScriptedWakeDetector(scripted={})
    assert all(d.detect_chunk(_silent()) is None for _ in range(20))


# ── OpenWakeWordDetector laziness ────────────────────────────────────────


def test_openwakeword_detector_does_not_import_at_construction():
    sentinel = sys.modules.pop("openwakeword", None)
    sentinel_model = sys.modules.pop("openwakeword.model", None)
    try:
        d = OpenWakeWordDetector(wake_words=["jarvis", "friday"], score_threshold=0.5)
        assert d._model is None  # noqa: SLF001
        assert "openwakeword" not in sys.modules
    finally:
        if sentinel is not None:
            sys.modules["openwakeword"] = sentinel
        if sentinel_model is not None:
            sys.modules["openwakeword.model"] = sentinel_model


def test_openwakeword_detector_buffers_before_frame_size():
    """A single small chunk shouldn't trigger an inference — buffer first."""

    # We don't want to actually load the model. Substitute a mock that
    # raises if called; if our buffering is correct it shouldn't be.
    d = OpenWakeWordDetector(wake_words=["jarvis"], score_threshold=0.5)
    d._model = object()  # noqa: SLF001 — pretend "loaded"

    class Boom:
        def predict(self, _):
            raise AssertionError("predict shouldn't run yet — buffer underfilled")

    d._model = Boom()  # noqa: SLF001
    # 200 samples is far below the 1280-sample frame size.
    chunk = np.zeros(200, dtype=np.float32)
    result = d.detect_chunk(chunk)
    assert result is None  # buffered, no inference


def test_openwakeword_detector_emits_best_match_above_threshold():
    """Inject a fake model with predictable scores and verify selection."""

    d = OpenWakeWordDetector(
        wake_words=["jarvis", "newton", "friday"], score_threshold=0.5
    )

    class FakeModel:
        def predict(self, _pcm):
            # Two above threshold; expect the larger one to win.
            return {"jarvis": 0.7, "newton": 0.85, "friday": 0.4}

    d._model = FakeModel()  # noqa: SLF001

    # Feed one full frame (1280 samples) to flush the buffer.
    full = np.full(1280, 0.1, dtype=np.float32)
    res = d.detect_chunk(full)
    assert res == WakeMatch(wake_word="newton", score=0.85)


def test_openwakeword_detector_below_threshold_returns_none():
    d = OpenWakeWordDetector(wake_words=["jarvis"], score_threshold=0.6)

    class FakeModel:
        def predict(self, _):
            return {"jarvis": 0.4}

    d._model = FakeModel()  # noqa: SLF001
    res = d.detect_chunk(np.zeros(1280, dtype=np.float32))
    assert res is None
