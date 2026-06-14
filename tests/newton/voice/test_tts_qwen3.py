"""Tests for newton.voice.tts.qwen3 — adapter contract + lazy load."""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np
import pytest

from newton.voice.tts.base import TTS, TTSResult, save_wav
from newton.voice.tts.qwen3 import Qwen3TTS

# ── TTS ABC ───────────────────────────────────────────────────────────────


def test_tts_abc_not_instantiable():
    with pytest.raises(TypeError):
        TTS()  # type: ignore[abstract]


def test_tts_subclass_requires_name():
    with pytest.raises(TypeError, match="must define 'name'"):

        class Nameless(TTS):
            name = ""

            def synthesize(self, text, *, language=None, voice_reference=None):  # noqa: ARG002
                return TTSResult(audio=np.zeros(1), sample_rate=16000)


# ── TTSResult / save_wav ─────────────────────────────────────────────────


def test_tts_result_duration():
    r = TTSResult(audio=np.zeros(16000), sample_rate=16000)
    assert r.duration_seconds == 1.0


def test_save_wav_roundtrip(tmp_path):
    sr = 16000
    audio = np.sin(2 * np.pi * 440 * np.linspace(0, 1, sr, dtype=np.float32))
    result = TTSResult(audio=audio.astype(np.float32), sample_rate=sr)
    path = tmp_path / "out.wav"
    save_wav(result, path)

    with wave.open(str(path), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == sr
        frames = wf.readframes(wf.getnframes())
    decoded = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32767.0
    np.testing.assert_allclose(decoded, audio, atol=1e-3)


def test_save_wav_clips_out_of_range(tmp_path):
    audio = np.array([2.5, -3.0, 0.5], dtype=np.float32)
    result = TTSResult(audio=audio, sample_rate=8000)
    path = tmp_path / "clip.wav"
    save_wav(result, path)
    with wave.open(str(path), "rb") as wf:
        decoded = np.frombuffer(wf.readframes(3), dtype=np.int16)
    # 2.5 → clipped to +1.0 → 32767; -3.0 → -1.0 → -32767.
    assert decoded[0] == 32767
    assert decoded[1] == -32767


# ── Qwen3TTS construction + size validation ─────────────────────────────


def test_qwen3_rejects_unknown_size():
    with pytest.raises(ValueError, match="model_size"):
        Qwen3TTS(model_size="100B")


def test_qwen3_name_embeds_size():
    """The fallback log keys off ``name``; size must be in it."""
    t06 = Qwen3TTS(model_size="0.6B", loader=lambda *_: None)
    t17 = Qwen3TTS(model_size="1.7B", loader=lambda *_: None)
    assert t06.name == "qwen3_tts_0.6b"
    assert t17.name == "qwen3_tts_1.7b"


# ── Laziness contract ────────────────────────────────────────────────────


def test_qwen3_does_not_import_qwen_tts_at_construction():
    sentinel = sys.modules.pop("qwen_tts", None)
    try:
        t = Qwen3TTS(model_size="0.6B", loader=lambda *_: None)
        assert t._model is None  # noqa: SLF001
        assert "qwen_tts" not in sys.modules
    finally:
        if sentinel is not None:
            sys.modules["qwen_tts"] = sentinel


def test_qwen3_does_not_call_loader_until_synthesize():
    calls = {"n": 0}

    def fake_loader(_size, _root):
        calls["n"] += 1
        return _FakeModel()

    t = Qwen3TTS(model_size="0.6B", loader=fake_loader)
    assert calls["n"] == 0
    t.synthesize("hello")
    assert calls["n"] == 1
    t.synthesize("again")
    # The model is cached — second synthesize doesn't reload.
    assert calls["n"] == 1


# ── synthesize behaviour with injected loader ────────────────────────────


class _FakeModel:
    """Mimics a qwen-tts model with a generate() that returns numpy."""

    def __init__(self) -> None:
        self.last_call: dict | None = None
        # Two seconds of a fixed-frequency tone — distinguishable from silence.
        self._wave = np.sin(
            2 * np.pi * 220 * np.linspace(0, 2, 48000, dtype=np.float32)
        )

    def generate(self, *, text, ref_audio, language):
        self.last_call = {"text": text, "ref_audio": ref_audio, "language": language}
        return self._wave


def _fake_loader(_size, _root):
    return _FakeModel()


def test_synthesize_returns_tts_result_with_numpy_audio():
    t = Qwen3TTS(model_size="0.6B", loader=_fake_loader)
    out = t.synthesize("hello")
    assert isinstance(out, TTSResult)
    assert out.audio.dtype == np.float32
    assert out.sample_rate > 0


def test_synthesize_passes_text_language_and_voice_reference_through():
    t = Qwen3TTS(model_size="0.6B", loader=_fake_loader)
    t.synthesize(
        "안녕하십니까", language="ko", voice_reference=Path("/tmp/jarvis-ko.wav")
    )
    fake = t._model  # noqa: SLF001
    assert fake.last_call == {
        "text": "안녕하십니까",
        "ref_audio": "/tmp/jarvis-ko.wav",
        "language": "ko",
    }


def test_synthesize_rejects_empty_text():
    t = Qwen3TTS(model_size="0.6B", loader=_fake_loader)
    with pytest.raises(ValueError, match="non-empty"):
        t.synthesize("   ")


def test_normalize_output_accepts_tuple():
    """A model that returns (audio, sr) tuple is handled."""

    class TupleModel:
        def generate(self, **_kw):
            return np.zeros(8000, dtype=np.float32), 24000

    t = Qwen3TTS(model_size="0.6B", loader=lambda *_: TupleModel())
    out = t.synthesize("x")
    assert out.sample_rate == 24000
    assert len(out.audio) == 8000


def test_normalize_output_accepts_dict():
    class DictModel:
        def generate(self, **_kw):
            return {"audio": np.zeros(2400, dtype=np.float32), "sample_rate": 12000}

    t = Qwen3TTS(model_size="1.7B", loader=lambda *_: DictModel())
    out = t.synthesize("x")
    assert out.sample_rate == 12000
    assert len(out.audio) == 2400


# ── missing-model-file branch ────────────────────────────────────────────


def test_default_loader_raises_when_weights_missing(tmp_path):
    """The shipped loader gives a clear error when the path is empty."""
    # Don't import qwen_tts (we don't have it); test the path-check
    # before the import would even run.
    from newton.voice.tts.qwen3 import _default_loader

    # Point at a directory that exists but has no 0.6B subdir.
    with pytest.raises(FileNotFoundError, match="weights not found"):
        _default_loader("0.6B", tmp_path)
