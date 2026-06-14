"""Tests for newton.voice.vad — VAD ABC, RmsVAD, SpeechSegmenter, lazy load."""

from __future__ import annotations

import numpy as np
import pytest

from newton.voice.config import VADConfig
from newton.voice.vad import (
    VAD,
    RmsVAD,
    SegmentEvent,
    SileroVAD,
    SpeechSegmenter,
    VADResult,
)

# ── ABC enforcement ────────────────────────────────────────────────────────


def test_vad_abc_not_instantiable():
    with pytest.raises(TypeError):
        VAD()  # type: ignore[abstract]


# ── RmsVAD (deterministic, no torch) ──────────────────────────────────────


def test_rms_vad_detects_loud_chunk_as_speech():
    vad = RmsVAD(threshold=0.05)
    # Loud chunk at amplitude ~0.3 → RMS = 0.3, > 0.05.
    chunk = np.full(512, 0.3, dtype=np.float32)
    result = vad.detect(chunk)
    assert isinstance(result, VADResult)
    assert result.is_speech is True
    assert result.probability == 1.0


def test_rms_vad_treats_silence_as_silence():
    vad = RmsVAD(threshold=0.05)
    chunk = np.zeros(512, dtype=np.float32)
    result = vad.detect(chunk)
    assert result.is_speech is False
    assert result.probability == 0.0


def test_rms_vad_probability_scales_with_amplitude():
    vad = RmsVAD(threshold=0.1)
    # RMS at threshold → probability 0.5
    chunk = np.full(512, 0.1, dtype=np.float32)
    res = vad.detect(chunk)
    assert res.probability == pytest.approx(0.5, abs=1e-3)


# ── SileroVAD laziness ────────────────────────────────────────────────────


def test_silero_vad_does_not_import_torch_at_construction():
    """Strategy D: model + torch load on first detect, not at module/class import."""
    import sys

    # Force the imports to be missing during construction. We're not
    # going to call detect, so the absence is fine.
    torch_was = sys.modules.pop("torch", None)
    silero_was = sys.modules.pop("silero_vad", None)
    try:
        vad = SileroVAD(threshold=0.5, sample_rate=16000)
        assert vad._model is None  # noqa: SLF001
        assert vad._torch is None  # noqa: SLF001
        # And neither was imported as a side effect.
        assert "torch" not in sys.modules
        assert "silero_vad" not in sys.modules
    finally:
        if torch_was is not None:
            sys.modules["torch"] = torch_was
        if silero_was is not None:
            sys.modules["silero_vad"] = silero_was


# ── SpeechSegmenter ──────────────────────────────────────────────────────


CFG = VADConfig(threshold=0.5, min_speech_chunks=3, min_silence_chunks=5)


def _speech_result(p: float = 0.9) -> VADResult:
    return VADResult(is_speech=True, probability=p)


def _silence_result() -> VADResult:
    return VADResult(is_speech=False, probability=0.0)


def test_segmenter_emits_speech_start_after_min_chunks():
    seg = SpeechSegmenter(config=CFG)
    events = []
    for i in range(CFG.min_speech_chunks):
        events.extend(seg.feed(i, _speech_result()))

    # Exactly one "speech_start" event, at the last (min_speech_chunks-th) chunk.
    assert events == [SegmentEvent("speech_start", CFG.min_speech_chunks - 1)]
    assert seg.in_speech is True


def test_segmenter_does_not_emit_for_blips():
    """Two speech chunks then silence — never crosses min_speech_chunks=3."""
    seg = SpeechSegmenter(config=CFG)
    out = []
    out.extend(seg.feed(0, _speech_result()))
    out.extend(seg.feed(1, _speech_result()))
    out.extend(seg.feed(2, _silence_result()))
    out.extend(seg.feed(3, _silence_result()))
    assert out == []
    assert seg.in_speech is False


def test_segmenter_emits_speech_end_after_silence_run():
    seg = SpeechSegmenter(config=CFG)
    # Get into speech state
    for i in range(CFG.min_speech_chunks):
        seg.feed(i, _speech_result())
    assert seg.in_speech is True

    # Feed silence until end fires
    end_events = []
    for i in range(CFG.min_silence_chunks):
        end_events.extend(seg.feed(CFG.min_speech_chunks + i, _silence_result()))

    assert end_events == [
        SegmentEvent("speech_end", CFG.min_speech_chunks + CFG.min_silence_chunks - 1)
    ]
    assert seg.in_speech is False


def test_segmenter_brief_silence_does_not_split_segment():
    seg = SpeechSegmenter(config=CFG)
    for i in range(CFG.min_speech_chunks):
        seg.feed(i, _speech_result())
    # A 2-chunk silence (below min_silence_chunks=5) should not end speech
    silence_events = []
    for i in range(2):
        silence_events.extend(seg.feed(CFG.min_speech_chunks + i, _silence_result()))
    assert silence_events == []
    assert seg.in_speech is True
    # Resuming speech is fine — no new "speech_start" because we never left.
    resume = seg.feed(CFG.min_speech_chunks + 2, _speech_result())
    assert resume == []


def test_segmenter_resets_state():
    seg = SpeechSegmenter(config=CFG)
    for i in range(CFG.min_speech_chunks):
        seg.feed(i, _speech_result())
    assert seg.in_speech is True
    seg.reset()
    assert seg.in_speech is False
    # And subsequent chunks behave as if from scratch.
    out = seg.feed(0, _silence_result())
    assert out == []


# ── End-to-end: source → VAD → segmenter ─────────────────────────────────


def test_pipeline_with_list_source_and_rms_vad():
    """Smoke test: chunks flow from source → VAD → segmenter cleanly."""
    from newton.voice.audio_source import ListSource

    # 3 silent, 4 loud, 8 silent → expect speech_start at index 4,
    # speech_end at index 6 + min_silence_chunks - 1 = 11 (12th chunk overall).
    silent = np.zeros(512, dtype=np.float32)
    loud = np.full(512, 0.3, dtype=np.float32)
    chunks = [silent] * 3 + [loud] * 4 + [silent] * 8
    src = ListSource(chunks=chunks, chunk_samples=512)
    vad = RmsVAD(threshold=0.05)
    seg = SpeechSegmenter(
        config=VADConfig(threshold=0.5, min_speech_chunks=3, min_silence_chunks=5)
    )

    events: list[SegmentEvent] = []
    for i, c in enumerate(src):
        events.extend(seg.feed(i, vad.detect(c)))

    kinds = [e.kind for e in events]
    assert kinds == ["speech_start", "speech_end"]
