"""Tests for newton.voice.tts.http_backend — RemoteQwen3TTS.

Mock the ``newton-tts`` service with respx so nothing here hits the
live container. Two things matter:

1. The POST body shape conforms to the service contract fixed by
   ``deploy/docker/tts/server.py`` — custom_voice for JARVIS,
   clone (with ref_audio_b64 + ref_text) for the Base model.
2. Strategy D — importing the HTTP backend must not pull torch or
   qwen_tts. The core stays GPU-library-free.
"""

from __future__ import annotations

import base64
import importlib
import io
import json
import sys
import wave

import httpx
import numpy as np
import pytest
import respx

from newton.voice.tts.base import TTSResult
from newton.voice.tts.http_backend import (
    DEFAULT_TTS_URL,
    RemoteQwen3TTS,
    TTSBackendError,
)

TEST_URL = "http://testhost:8081"


# ── helpers ─────────────────────────────────────────────────────────────


def _make_wav_b64(audio: np.ndarray, sr: int) -> str:
    """Build a base64-encoded 16-bit PCM mono WAV — matches the service."""
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _ok_response(sr: int = 24000, samples: int = 4800) -> httpx.Response:
    tone = np.sin(2 * np.pi * 440 * np.linspace(0, samples / sr, samples)).astype(
        np.float32
    )
    return httpx.Response(
        200,
        json={"audio_b64": _make_wav_b64(tone, sr), "sample_rate": sr},
    )


def _body(route) -> dict:  # noqa: ANN001
    return json.loads(route.calls.last.request.read())


# ── Strategy D import guard ─────────────────────────────────────────────


def test_http_backend_does_not_import_torch_or_qwen_tts():
    """The HTTP backend stays in the torch-free core.

    Pop the cached module + any prior torch/qwen_tts entries so we
    measure only what *this* import path drags in. Restore the original
    cached module afterwards so the class object stays identity-stable
    for the isinstance checks in the rest of the file.
    """
    saved_hb = sys.modules.pop("newton.voice.tts.http_backend", None)
    saved_torch = sys.modules.pop("torch", None)
    saved_qwen = sys.modules.pop("qwen_tts", None)
    try:
        importlib.import_module("newton.voice.tts.http_backend")
        assert "qwen_tts" not in sys.modules
        assert "torch" not in sys.modules
    finally:
        if saved_hb is not None:
            sys.modules["newton.voice.tts.http_backend"] = saved_hb
        if saved_torch is not None:
            sys.modules["torch"] = saved_torch
        if saved_qwen is not None:
            sys.modules["qwen_tts"] = saved_qwen


# ── defaults ────────────────────────────────────────────────────────────


def test_default_url_matches_compose():
    """The default URL matches deploy/docker/tts/compose.yaml port mapping."""
    assert DEFAULT_TTS_URL == "http://localhost:8081"


def test_url_trailing_slash_is_stripped():
    t = RemoteQwen3TTS(url="http://host:8081/")
    assert t._url == "http://host:8081"  # noqa: SLF001


# ── custom_voice mode ───────────────────────────────────────────────────


def test_custom_voice_post_body_shape_for_jarvis():
    t = RemoteQwen3TTS(name="qwen3_tts_jarvis", speaker="jarvis", url=TEST_URL)
    with respx.mock:
        route = respx.post(f"{TEST_URL}/synthesize").mock(return_value=_ok_response())
        result = t.synthesize("Good evening, sir.", language="en")
    assert route.called
    assert _body(route) == {
        "text": "Good evening, sir.",
        "language": "english",  # short code translated at the boundary
        "mode": "custom_voice",
        "speaker": "jarvis",
    }
    assert isinstance(result, TTSResult)
    assert result.audio.dtype == np.float32
    assert result.sample_rate == 24000


def test_custom_voice_ignores_voice_reference_and_ref_text(tmp_path):
    """Mode is fixed at construction; stray refs do not switch to clone."""
    t = RemoteQwen3TTS(speaker="jarvis", url=TEST_URL)
    with respx.mock:
        route = respx.post(f"{TEST_URL}/synthesize").mock(return_value=_ok_response())
        t.synthesize(
            "안녕하십니까.",
            language="ko",
            voice_reference=tmp_path / "ignored.wav",
            ref_text="anything",
        )
    payload = _body(route)
    assert payload["mode"] == "custom_voice"
    assert payload["speaker"] == "jarvis"
    assert "ref_audio_b64" not in payload
    assert payload["language"] == "korean"


# ── clone mode ──────────────────────────────────────────────────────────


def test_clone_post_body_includes_ref_audio_b64_and_ref_text(tmp_path):
    sample_path = tmp_path / "donor.wav"
    sample_path.write_bytes(b"RIFF...fake-wav-bytes...DATA")

    t = RemoteQwen3TTS(name="qwen3_tts_base", url=TEST_URL)
    with respx.mock:
        route = respx.post(f"{TEST_URL}/synthesize").mock(return_value=_ok_response())
        t.synthesize(
            "Right away, sir.",
            language="en",
            voice_reference=sample_path,
            ref_text="Good evening, sir.",
        )
    payload = _body(route)
    assert payload["mode"] == "clone"
    assert payload["language"] == "english"
    assert payload["ref_text"] == "Good evening, sir."
    assert base64.b64decode(payload["ref_audio_b64"]) == b"RIFF...fake-wav-bytes...DATA"
    assert "speaker" not in payload


def test_clone_without_ref_text_raises(tmp_path):
    sample_path = tmp_path / "donor.wav"
    sample_path.write_bytes(b"x")
    t = RemoteQwen3TTS(url=TEST_URL)
    with respx.mock:
        respx.post(f"{TEST_URL}/synthesize")  # not expected to be called
        with pytest.raises(ValueError, match="ref_text"):
            t.synthesize(
                "hi", language="en", voice_reference=sample_path, ref_text=None
            )
        with pytest.raises(ValueError, match="ref_text"):
            t.synthesize(
                "hi", language="en", voice_reference=sample_path, ref_text="   "
            )


def test_synthesize_without_speaker_or_reference_raises():
    t = RemoteQwen3TTS(url=TEST_URL)
    with pytest.raises(ValueError, match="speaker"):
        t.synthesize("hi", language="en")


def test_synthesize_rejects_empty_text():
    t = RemoteQwen3TTS(speaker="jarvis", url=TEST_URL)
    with pytest.raises(ValueError, match="non-empty"):
        t.synthesize("   ", language="en")


def test_synthesize_requires_language():
    t = RemoteQwen3TTS(speaker="jarvis", url=TEST_URL)
    with pytest.raises(ValueError, match="language"):
        t.synthesize("hello")


def test_clone_accepts_string_voice_reference(tmp_path):
    p = tmp_path / "donor.wav"
    p.write_bytes(b"abc")
    t = RemoteQwen3TTS(url=TEST_URL)
    with respx.mock:
        route = respx.post(f"{TEST_URL}/synthesize").mock(return_value=_ok_response())
        t.synthesize("hi", language="en", voice_reference=str(p), ref_text="ref")
    payload = _body(route)
    assert payload["mode"] == "clone"
    assert base64.b64decode(payload["ref_audio_b64"]) == b"abc"


def test_clone_missing_voice_reference_file_wraps_in_backend_error(tmp_path):
    """Reading a non-existent voice_reference fails as a TTSBackendError."""
    t = RemoteQwen3TTS(url=TEST_URL)
    with pytest.raises(TTSBackendError, match="voice_reference"):
        t.synthesize(
            "hi",
            language="en",
            voice_reference=tmp_path / "does-not-exist.wav",
            ref_text="anything",
        )


# ── response decode ─────────────────────────────────────────────────────


def test_response_audio_decoded_to_float32_and_sample_rate_passed_through():
    sr = 22050
    samples = 8000
    tone = np.sin(2 * np.pi * 220 * np.linspace(0, 1, samples)).astype(np.float32)
    t = RemoteQwen3TTS(speaker="jarvis", url=TEST_URL)
    with respx.mock:
        respx.post(f"{TEST_URL}/synthesize").mock(
            return_value=httpx.Response(
                200,
                json={"audio_b64": _make_wav_b64(tone, sr), "sample_rate": sr},
            )
        )
        result = t.synthesize("x", language="en")
    assert result.sample_rate == sr
    assert result.audio.dtype == np.float32
    assert len(result.audio) == samples


def test_response_missing_audio_b64_raises():
    t = RemoteQwen3TTS(speaker="jarvis", url=TEST_URL)
    with respx.mock:
        respx.post(f"{TEST_URL}/synthesize").mock(
            return_value=httpx.Response(200, json={"sample_rate": 24000})
        )
        with pytest.raises(TTSBackendError, match="missing audio_b64"):
            t.synthesize("x", language="en")


# ── HTTP error handling ─────────────────────────────────────────────────


def test_non_200_response_raises_backend_error():
    t = RemoteQwen3TTS(speaker="jarvis", url=TEST_URL)
    with respx.mock:
        respx.post(f"{TEST_URL}/synthesize").mock(
            return_value=httpx.Response(500, text="boom")
        )
        with pytest.raises(TTSBackendError, match="HTTP 500"):
            t.synthesize("x", language="en")


def test_transport_error_raises_backend_error():
    t = RemoteQwen3TTS(speaker="jarvis", url=TEST_URL)
    with respx.mock:
        respx.post(f"{TEST_URL}/synthesize").mock(
            side_effect=httpx.ConnectError("refused")
        )
        with pytest.raises(TTSBackendError, match="newton-tts request failed"):
            t.synthesize("x", language="en")


def test_backend_error_is_runtime_error():
    """The fallback chain catches RuntimeError — keep the subclass relation."""
    assert issubclass(TTSBackendError, RuntimeError)


# ── language mapping ────────────────────────────────────────────────────


@pytest.mark.parametrize("short,full", [("ko", "korean"), ("en", "english")])
def test_language_short_codes_are_translated(short: str, full: str):
    t = RemoteQwen3TTS(speaker="jarvis", url=TEST_URL)
    with respx.mock:
        route = respx.post(f"{TEST_URL}/synthesize").mock(return_value=_ok_response())
        t.synthesize("hello", language=short)
    assert _body(route)["language"] == full


# ── health() ────────────────────────────────────────────────────────────


def test_health_true_on_200():
    t = RemoteQwen3TTS(url=TEST_URL)
    with respx.mock:
        respx.get(f"{TEST_URL}/health").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        assert t.health() is True


def test_health_false_on_503():
    t = RemoteQwen3TTS(url=TEST_URL)
    with respx.mock:
        respx.get(f"{TEST_URL}/health").mock(
            return_value=httpx.Response(503, text="not ready")
        )
        assert t.health() is False


def test_health_false_on_transport_error():
    t = RemoteQwen3TTS(url=TEST_URL)
    with respx.mock:
        respx.get(f"{TEST_URL}/health").mock(side_effect=httpx.ConnectError("refused"))
        assert t.health() is False


# ── factory wiring ──────────────────────────────────────────────────────


def test_make_engine_factory_remote_returns_http_backend():
    from newton.voice.config import TTSConfig
    from newton.voice.tts.router import make_engine_factory

    cfg = TTSConfig(backend="remote", url=TEST_URL, timeout_s=5.0)
    factory = make_engine_factory(cfg)
    e_jarvis = factory("qwen3_tts_jarvis")
    e_base = factory("qwen3_tts_base")
    assert isinstance(e_jarvis, RemoteQwen3TTS)
    assert e_jarvis.speaker == "jarvis"
    assert e_jarvis.name == "qwen3_tts_jarvis"
    assert isinstance(e_base, RemoteQwen3TTS)
    assert e_base.speaker is None
    assert e_base.name == "qwen3_tts_base"
    # url + timeout threaded through
    assert e_jarvis._url == TEST_URL  # noqa: SLF001
    assert e_jarvis._timeout == 5.0  # noqa: SLF001


def test_make_engine_factory_local_returns_local_adapter():
    """Local mode falls back to the in-process Qwen3TTS, not the HTTP backend."""
    from newton.voice.config import TTSConfig
    from newton.voice.tts.qwen3 import Qwen3TTS
    from newton.voice.tts.router import make_engine_factory

    cfg = TTSConfig(backend="local")
    factory = make_engine_factory(cfg)
    e = factory("qwen3_tts_base")
    assert isinstance(e, Qwen3TTS)
    assert not isinstance(e, RemoteQwen3TTS)


def test_make_engine_factory_chatterbox_is_local_in_both_modes():
    """chatterbox has no HTTP service — always local."""
    from newton.voice.config import TTSConfig
    from newton.voice.tts.chatterbox import ChatterboxTTS
    from newton.voice.tts.router import make_engine_factory

    for backend in ("local", "remote"):
        factory = make_engine_factory(TTSConfig(backend=backend))
        assert isinstance(factory("chatterbox"), ChatterboxTTS)


def test_make_engine_factory_rejects_unknown_name():
    from newton.voice.config import TTSConfig
    from newton.voice.tts.router import make_engine_factory

    factory = make_engine_factory(TTSConfig(backend="remote"))
    with pytest.raises(ValueError, match="unknown TTS engine"):
        factory("brand_x")


# ── config knob plumbed through ─────────────────────────────────────────


def test_tts_config_defaults_remote():
    from newton.voice.config import TTSConfig

    cfg = TTSConfig()
    assert cfg.backend == "remote"
    assert cfg.url == DEFAULT_TTS_URL
    assert cfg.timeout_s == pytest.approx(60.0)


def test_tts_config_rejects_unknown_backend():
    from pydantic import ValidationError

    from newton.voice.config import TTSConfig

    with pytest.raises(ValidationError):
        TTSConfig(backend="cloud")  # type: ignore[arg-type]
