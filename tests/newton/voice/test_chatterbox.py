"""Tests for newton.voice.tts.chatterbox — lazy load + output coercion."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from newton.voice.tts.base import TTSResult
from newton.voice.tts.chatterbox import ChatterboxTTS


class _FakeModel:
    def __init__(self) -> None:
        self.last_call: dict | None = None
        self._wave = np.zeros(8000, dtype=np.float32)

    def generate(self, *, text, audio_prompt_path):
        self.last_call = {"text": text, "audio_prompt_path": audio_prompt_path}
        return self._wave


def _fake_loader(_root):
    return _FakeModel()


# ── Laziness ─────────────────────────────────────────────────────────────


def test_chatterbox_does_not_import_at_construction():
    sentinel = sys.modules.pop("chatterbox", None)
    sentinel_tts = sys.modules.pop("chatterbox.tts", None)
    try:
        t = ChatterboxTTS(loader=_fake_loader)
        assert t._model is None  # noqa: SLF001
        assert "chatterbox" not in sys.modules
        assert "chatterbox.tts" not in sys.modules
    finally:
        if sentinel is not None:
            sys.modules["chatterbox"] = sentinel
        if sentinel_tts is not None:
            sys.modules["chatterbox.tts"] = sentinel_tts


def test_chatterbox_does_not_call_loader_until_synthesize():
    calls = {"n": 0}

    def fake_loader(_root):
        calls["n"] += 1
        return _FakeModel()

    t = ChatterboxTTS(loader=fake_loader)
    assert calls["n"] == 0
    t.synthesize("hello")
    assert calls["n"] == 1
    t.synthesize("again")
    assert calls["n"] == 1  # cached


# ── Engine identity for the fallback log ────────────────────────────────


def test_chatterbox_engine_name():
    t = ChatterboxTTS(loader=_fake_loader)
    assert t.name == "chatterbox"


# ── synthesize behaviour ────────────────────────────────────────────────


def test_synthesize_passes_text_and_voice_reference():
    t = ChatterboxTTS(loader=_fake_loader)
    t.synthesize(
        "Right away, sir.",
        language="en",
        voice_reference=Path("/tmp/jarvis-en.wav"),
    )
    fake: _FakeModel = t._model  # noqa: SLF001
    assert fake.last_call == {
        "text": "Right away, sir.",
        "audio_prompt_path": "/tmp/jarvis-en.wav",
    }


def test_synthesize_rejects_empty_text():
    t = ChatterboxTTS(loader=_fake_loader)
    with pytest.raises(ValueError, match="non-empty"):
        t.synthesize("   ")


def test_synthesize_warns_on_non_english(caplog):
    t = ChatterboxTTS(loader=_fake_loader)
    import logging

    with caplog.at_level(logging.WARNING, logger="newton.voice.tts.chatterbox"):
        t.synthesize("hello", language="ko")
    assert any(
        "non-English" in r.message and "language=" in r.message for r in caplog.records
    )


def test_normalize_output_tuple_and_dict():
    class TupleModel:
        def generate(self, **_kw):
            return np.zeros(8000, dtype=np.float32), 22050

    class DictModel:
        def generate(self, **_kw):
            return {"audio": np.zeros(1000, dtype=np.float32), "sample_rate": 16000}

    t1 = ChatterboxTTS(loader=lambda _: TupleModel())
    r1 = t1.synthesize("x", language="en")
    assert r1.sample_rate == 22050

    t2 = ChatterboxTTS(loader=lambda _: DictModel())
    r2 = t2.synthesize("x", language="en")
    assert r2.sample_rate == 16000


def test_default_loader_raises_on_missing_root(tmp_path):
    from newton.voice.tts.chatterbox import _default_loader

    with pytest.raises(FileNotFoundError, match="weights not found"):
        _default_loader(tmp_path / "does-not-exist")


def test_returns_tts_result():
    t = ChatterboxTTS(loader=_fake_loader)
    out = t.synthesize("hi")
    assert isinstance(out, TTSResult)
    assert out.audio.dtype == np.float32
