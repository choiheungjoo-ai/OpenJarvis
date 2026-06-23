"""Tests for newton.voice.tts.qwen3 — verified clone + custom-voice API.

Covers the two synthesis modes against fake models, the language-code
translation at the adapter boundary, and the Strategy-D guarantee that
``qwen_tts`` / torch never import at module load.
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np
import pytest

from newton.voice.tts.base import TTS, TTSResult, save_wav
from newton.voice.tts.qwen3 import Qwen3TTS, _to_full_language

# ── TTS ABC ───────────────────────────────────────────────────────────────


def test_tts_abc_not_instantiable():
    with pytest.raises(TypeError):
        TTS()  # type: ignore[abstract]


def test_tts_subclass_requires_name():
    with pytest.raises(TypeError, match="must define 'name'"):

        class Nameless(TTS):
            name = ""

            def synthesize(
                self, text, *, language=None, voice_reference=None, ref_text=None
            ):  # noqa: ARG002
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


# ── Qwen3TTS construction + identity ─────────────────────────────────────


def test_qwen3_default_name_and_no_speaker():
    t = Qwen3TTS(loader=lambda _path: _CloneModel())
    assert t.name == "qwen3_tts"
    assert t.speaker is None


def test_qwen3_custom_name_and_speaker_carried():
    """The fallback log keys off ``name``; the engine mode keys off ``speaker``."""
    t_base = Qwen3TTS(name="qwen3_tts_base", loader=lambda _p: _CloneModel())
    t_jarvis = Qwen3TTS(
        name="qwen3_tts_jarvis",
        speaker="jarvis",
        loader=lambda _p: _CustomModel(),
    )
    assert t_base.name == "qwen3_tts_base"
    assert t_base.speaker is None
    assert t_jarvis.name == "qwen3_tts_jarvis"
    assert t_jarvis.speaker == "jarvis"


# ── Laziness contract (Strategy D) ───────────────────────────────────────


def test_qwen3_does_not_import_qwen_tts_at_module_load():
    """Importing newton.voice.tts.qwen3 must not pull qwen_tts or torch."""
    # If a prior test imported qwen_tts, pop it so we measure only what
    # *this* import path drags in.
    for mod in ("qwen_tts", "torch"):
        sys.modules.pop(mod, None)
    # Re-import the adapter module to force its side effects.
    sys.modules.pop("newton.voice.tts.qwen3", None)
    import newton.voice.tts.qwen3  # noqa: F401, PLC0415

    assert "qwen_tts" not in sys.modules
    assert "torch" not in sys.modules


def test_qwen3_does_not_import_qwen_tts_at_construction():
    sentinel = sys.modules.pop("qwen_tts", None)
    try:
        t = Qwen3TTS(loader=lambda _path: None)
        assert t._model is None  # noqa: SLF001
        assert "qwen_tts" not in sys.modules
    finally:
        if sentinel is not None:
            sys.modules["qwen_tts"] = sentinel


def test_qwen3_does_not_call_loader_until_synthesize():
    calls = {"n": 0}

    def fake_loader(_path):
        calls["n"] += 1
        return _CustomModel()

    t = Qwen3TTS(speaker="jarvis", loader=fake_loader)
    assert calls["n"] == 0
    t.synthesize("hello", language="en")
    assert calls["n"] == 1
    t.synthesize("again", language="en")
    # The model is cached — second synthesize doesn't reload.
    assert calls["n"] == 1


# ── language mapping ─────────────────────────────────────────────────────


def test_to_full_language_short_codes():
    assert _to_full_language("ko") == "korean"
    assert _to_full_language("en") == "english"


def test_to_full_language_passthrough_for_full_names():
    assert _to_full_language("korean") == "korean"
    assert _to_full_language("english") == "english"


def test_to_full_language_none_is_passthrough():
    assert _to_full_language(None) is None


def test_to_full_language_rejects_unknown():
    with pytest.raises(ValueError, match="unsupported Qwen3-TTS language"):
        _to_full_language("ja")


# ── fake models for the two API surfaces ────────────────────────────────


class _CustomModel:
    """Mimics the fine-tuned model's ``generate_custom_voice``."""

    def __init__(self) -> None:
        self.last_call: dict | None = None
        self._wave = np.sin(
            2 * np.pi * 220 * np.linspace(0, 2, 48000, dtype=np.float32)
        )

    def generate_custom_voice(self, *, text, speaker, language):
        self.last_call = {"text": text, "speaker": speaker, "language": language}
        return [self._wave], 24000

    def generate_voice_clone(self, **_kw):  # noqa: D401
        raise AssertionError(
            "custom-voice model must not be asked for generate_voice_clone"
        )


class _CloneModel:
    """Mimics the Base model's ``generate_voice_clone``."""

    def __init__(self) -> None:
        self.last_call: dict | None = None
        self._wave = np.sin(
            2 * np.pi * 220 * np.linspace(0, 2, 48000, dtype=np.float32)
        )

    def generate_voice_clone(self, *, text, language, ref_audio, ref_text):
        self.last_call = {
            "text": text,
            "language": language,
            "ref_audio": ref_audio,
            "ref_text": ref_text,
        }
        return [self._wave], 24000

    def generate_custom_voice(self, **_kw):  # noqa: D401
        raise AssertionError("clone model must not be asked for generate_custom_voice")


# ── custom-voice mode ───────────────────────────────────────────────────


def test_custom_voice_calls_generate_custom_voice_with_full_language():
    fake = _CustomModel()
    t = Qwen3TTS(
        name="qwen3_tts_jarvis",
        speaker="jarvis",
        loader=lambda _p: fake,
    )
    t.synthesize("Good evening, sir.", language="en")
    assert fake.last_call == {
        "text": "Good evening, sir.",
        "speaker": "jarvis",
        "language": "english",  # short code translated at the adapter boundary
    }


def test_custom_voice_ignores_voice_reference_and_ref_text():
    """The mode is fixed by construction — caller-supplied refs are inert."""
    fake = _CustomModel()
    t = Qwen3TTS(speaker="jarvis", loader=lambda _p: fake)
    t.synthesize(
        "안녕하십니까, sir.",
        language="ko",
        voice_reference=Path("/tmp/should-be-ignored.wav"),
        ref_text="anything",
    )
    assert fake.last_call == {
        "text": "안녕하십니까, sir.",
        "speaker": "jarvis",
        "language": "korean",
    }


# ── clone mode ──────────────────────────────────────────────────────────


def test_clone_calls_generate_voice_clone_with_ref_audio_and_ref_text():
    fake = _CloneModel()
    t = Qwen3TTS(name="qwen3_tts_base", loader=lambda _p: fake)
    t.synthesize(
        "Right away, sir.",
        language="en",
        voice_reference=Path("/tmp/jarvis-en.wav"),
        ref_text="Good evening, sir.",
    )
    assert fake.last_call == {
        "text": "Right away, sir.",
        "language": "english",
        "ref_audio": "/tmp/jarvis-en.wav",
        "ref_text": "Good evening, sir.",
    }


def test_clone_without_ref_text_raises():
    """Mismatched / missing ref_text mangles output — fail loud at the boundary."""
    fake = _CloneModel()
    t = Qwen3TTS(loader=lambda _p: fake)
    with pytest.raises(ValueError, match="ref_text"):
        t.synthesize(
            "hi",
            language="en",
            voice_reference=Path("/tmp/x.wav"),
            ref_text=None,
        )
    with pytest.raises(ValueError, match="ref_text"):
        t.synthesize(
            "hi",
            language="en",
            voice_reference=Path("/tmp/x.wav"),
            ref_text="   ",
        )
    assert fake.last_call is None  # never called


def test_clone_without_voice_reference_or_speaker_raises():
    t = Qwen3TTS(loader=lambda _p: _CloneModel())
    with pytest.raises(ValueError, match="speaker"):
        t.synthesize("hi", language="en")


def test_synthesize_rejects_empty_text():
    t = Qwen3TTS(speaker="jarvis", loader=lambda _p: _CustomModel())
    with pytest.raises(ValueError, match="non-empty"):
        t.synthesize("   ", language="en")


# ── output normalization ────────────────────────────────────────────────


def test_synthesize_returns_tts_result_with_numpy_audio():
    t = Qwen3TTS(speaker="jarvis", loader=lambda _p: _CustomModel())
    out = t.synthesize("hello", language="en")
    assert isinstance(out, TTSResult)
    assert out.audio.dtype == np.float32
    assert out.sample_rate > 0


def test_normalize_output_takes_first_wav_from_list_tuple():
    """The verified API returns ``(list[np.ndarray], sr)`` — adapter takes [0]."""

    class TwoWavModel:
        def generate_custom_voice(self, **_kw):
            first = np.full(8000, 0.5, dtype=np.float32)
            second = np.full(8000, -0.5, dtype=np.float32)  # would be wrong pick
            return [first, second], 22050

    t = Qwen3TTS(speaker="jarvis", loader=lambda _p: TwoWavModel())
    out = t.synthesize("x", language="en")
    assert out.sample_rate == 22050
    assert len(out.audio) == 8000
    # First wav is +0.5 — confirms we took [0].
    assert float(out.audio[0]) == pytest.approx(0.5)


def test_normalize_output_accepts_tuple_array():
    """Legacy shape ``(np.ndarray, sr)`` still works in case upstream tweaks."""

    class TupleModel:
        def generate_custom_voice(self, **_kw):
            return np.zeros(8000, dtype=np.float32), 24000

    t = Qwen3TTS(speaker="jarvis", loader=lambda _p: TupleModel())
    out = t.synthesize("x", language="en")
    assert out.sample_rate == 24000
    assert len(out.audio) == 8000


def test_normalize_output_accepts_dict():
    class DictModel:
        def generate_custom_voice(self, **_kw):
            return {"audio": np.zeros(2400, dtype=np.float32), "sample_rate": 12000}

    t = Qwen3TTS(speaker="jarvis", loader=lambda _p: DictModel())
    out = t.synthesize("x", language="en")
    assert out.sample_rate == 12000
    assert len(out.audio) == 2400


# ── missing-model-file branch ────────────────────────────────────────────


def test_default_loader_raises_when_weights_missing(tmp_path):
    """The shipped loader gives a clear error when the path is empty."""
    from newton.voice.tts.qwen3 import _default_loader

    with pytest.raises(FileNotFoundError, match="weights not found"):
        _default_loader(tmp_path / "does-not-exist")
