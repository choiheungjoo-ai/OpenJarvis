"""Tests for newton.voice.stt — STT ABC + WhisperSTT lazy + transcribe."""

from __future__ import annotations

import logging
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from newton.voice.stt.base import STT, Transcription
from newton.voice.stt.whisper import WhisperSTT

# ── ABC + Transcription ──────────────────────────────────────────────────


def test_stt_abc_not_instantiable():
    with pytest.raises(TypeError):
        STT()  # type: ignore[abstract]


def test_stt_subclass_requires_name():
    with pytest.raises(TypeError, match="must define 'name'"):

        class Nameless(STT):
            name = ""

            def transcribe(self, audio, **kwargs):  # noqa: ARG002
                return Transcription(text="", language="en", duration_seconds=0)


def test_transcription_dataclass_defaults():
    t = Transcription(text="hi", language="en", duration_seconds=1.5)
    assert t.segments == []


# ── WhisperSTT laziness ─────────────────────────────────────────────────


def test_whisper_does_not_import_faster_whisper_at_construction():
    sentinel = sys.modules.pop("faster_whisper", None)
    try:
        s = WhisperSTT(loader=lambda *_: None)
        assert s._model is None  # noqa: SLF001
        assert "faster_whisper" not in sys.modules
    finally:
        if sentinel is not None:
            sys.modules["faster_whisper"] = sentinel


def test_whisper_does_not_call_loader_until_transcribe():
    calls = {"n": 0}

    def fake_loader(_root, _ct):
        calls["n"] += 1
        return _FakeModel()

    s = WhisperSTT(loader=fake_loader)
    assert calls["n"] == 0
    s.transcribe(np.zeros(16000, dtype=np.float32))
    assert calls["n"] == 1
    s.transcribe(np.zeros(16000, dtype=np.float32))
    assert calls["n"] == 1  # cached


def test_default_loader_raises_on_missing_root(tmp_path):
    from newton.voice.stt.whisper import _default_loader

    with pytest.raises(FileNotFoundError, match="weights not found"):
        _default_loader(tmp_path / "missing", "int8")


# ── transcribe contract ─────────────────────────────────────────────────


def _seg(start: float, end: float, text: str):
    return SimpleNamespace(start=start, end=end, text=text)


class _FakeModel:
    """Mimics a faster-whisper model: .transcribe → (iter_segments, info)."""

    def __init__(
        self,
        text_pieces: list[str] | None = None,
        language: str = "en",
        duration: float = 1.0,
    ) -> None:
        # Use ``is None`` so an explicit empty list stays empty.
        self._pieces = text_pieces if text_pieces is not None else [" hello"]
        self._language = language
        self._duration = duration
        self.last_call: dict | None = None

    def transcribe(
        self,
        audio,
        *,
        language=None,
        initial_prompt=None,
        beam_size=5,
        vad_filter=False,
    ):
        self.last_call = {
            "language": language,
            "initial_prompt": initial_prompt,
            "beam_size": beam_size,
            "vad_filter": vad_filter,
        }
        segments = [_seg(i * 0.5, (i + 1) * 0.5, p) for i, p in enumerate(self._pieces)]
        info = SimpleNamespace(language=self._language, duration=self._duration)
        return iter(segments), info


def test_transcribe_returns_concatenated_text():
    s = WhisperSTT(loader=lambda *_: _FakeModel(text_pieces=[" hello", " world"]))
    out = s.transcribe(np.zeros(16000, dtype=np.float32))
    assert isinstance(out, Transcription)
    assert out.text == "hello world"
    assert out.language == "en"
    assert out.duration_seconds == 1.0
    assert len(out.segments) == 2
    assert out.segments[0]["text"] == " hello"


def test_transcribe_passes_language_and_initial_prompt():
    fake = _FakeModel(language="ko")
    s = WhisperSTT(loader=lambda *_: fake)
    s.transcribe(
        np.zeros(16000, dtype=np.float32),
        language="ko",
        initial_prompt="Domain context: Newton, BGE-M3",
    )
    assert fake.last_call == {
        "language": "ko",
        "initial_prompt": "Domain context: Newton, BGE-M3",
        "beam_size": 5,
        "vad_filter": False,
    }


def test_transcribe_auto_detect_language():
    fake = _FakeModel(language="ko")
    s = WhisperSTT(loader=lambda *_: fake)
    out = s.transcribe(np.zeros(16000, dtype=np.float32))  # no pin
    assert fake.last_call["language"] is None
    assert out.language == "ko"


def test_transcribe_rejects_multidim_audio():
    s = WhisperSTT(loader=lambda *_: _FakeModel())
    with pytest.raises(ValueError, match="mono"):
        s.transcribe(np.zeros((2, 16000), dtype=np.float32))


def test_transcribe_warns_on_non_16k_sample_rate(caplog):
    s = WhisperSTT(loader=lambda *_: _FakeModel())
    with caplog.at_level(logging.WARNING, logger="newton.voice.stt.whisper"):
        s.transcribe(np.zeros(8000, dtype=np.float32), sample_rate=8000)
    assert any("sample_rate" in r.message for r in caplog.records)


def test_whisper_engine_name():
    s = WhisperSTT(loader=lambda *_: _FakeModel())
    assert s.name == "whisper_large_v3"


def test_transcribe_handles_empty_segments():
    s = WhisperSTT(loader=lambda *_: _FakeModel(text_pieces=[]))
    out = s.transcribe(np.zeros(16000, dtype=np.float32))
    assert out.text == ""
    assert out.segments == []
