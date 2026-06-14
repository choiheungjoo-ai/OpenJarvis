"""Tests for newton.voice.audio_source — pure plumbing, no real mic."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from newton.voice.audio_source import (
    AudioSource,
    FileSource,
    ListSource,
)

# ── ABC enforcement ───────────────────────────────────────────────────────


def test_audio_source_is_abstract():
    """Subclasses must implement start / read / close."""
    with pytest.raises(TypeError):
        AudioSource()  # type: ignore[abstract]


# ── ListSource (test workhorse) ───────────────────────────────────────────


def test_list_source_yields_chunks_in_order():
    chunks = [
        np.array([0.1, 0.2, 0.3], dtype=np.float32),
        np.array([0.4, 0.5, 0.6], dtype=np.float32),
    ]
    src = ListSource(chunks=chunks, sample_rate=16000, chunk_samples=3)
    out = list(src)
    assert len(out) == 2
    np.testing.assert_array_almost_equal(out[0], chunks[0])
    np.testing.assert_array_almost_equal(out[1], chunks[1])


def test_list_source_returns_none_when_exhausted():
    src = ListSource(chunks=[np.zeros(3, dtype=np.float32)])
    src.start()
    assert src.read() is not None
    assert src.read() is None  # exhausted


def test_list_source_close_makes_read_return_none():
    src = ListSource(chunks=[np.zeros(3, dtype=np.float32)])
    src.start()
    src.close()
    assert src.read() is None


def test_list_source_can_be_restarted():
    """start() resets the position so the same source is reusable."""
    chunks = [np.array([1.0], dtype=np.float32)]
    src = ListSource(chunks=chunks)
    list(src)
    list(src)  # second pass over the same source


# ── FileSource (WAV via stdlib wave) ───────────────────────────────────────


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int = 16000) -> None:
    """Helper: write a mono 16-bit PCM WAV with the given samples in [-1, 1]."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes((samples * 32767).clip(-32768, 32767).astype(np.int16).tobytes())


def test_file_source_reads_chunks_from_wav(tmp_path):
    wav_path = tmp_path / "hello.wav"
    # 1 second of 16 kHz sine wave, 1024 samples per chunk.
    t = np.linspace(0, 1, 16000, endpoint=False, dtype=np.float32)
    samples = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    _write_wav(wav_path, samples)

    src = FileSource(path=wav_path, chunk_samples=1024)
    chunks = list(src)

    # 16000 / 1024 = 15.625 → 16 chunks total (last one padded to width)
    assert len(chunks) == 16
    for c in chunks:
        assert c.dtype == np.float32
        assert len(c) == 1024


def test_file_source_pads_short_tail(tmp_path):
    wav_path = tmp_path / "short.wav"
    # 100 samples → last chunk needs padding to chunk_samples=512.
    samples = np.linspace(0, 1, 100, dtype=np.float32)
    _write_wav(wav_path, samples)

    src = FileSource(path=wav_path, chunk_samples=512)
    chunks = list(src)
    assert len(chunks) == 1
    assert len(chunks[0]) == 512  # padded
    # The padded tail is zeros — the original data lives in the head.
    np.testing.assert_array_almost_equal(chunks[0][:100], samples, decimal=4)
    np.testing.assert_array_equal(chunks[0][100:], np.zeros(412, dtype=np.float32))


def test_file_source_rejects_unexpected_sample_rate(tmp_path):
    wav_path = tmp_path / "44k.wav"
    samples = np.zeros(1000, dtype=np.float32)
    _write_wav(wav_path, samples, sample_rate=44100)
    src = FileSource(path=wav_path, expected_sample_rate=16000)
    with pytest.raises(ValueError, match="sample rate"):
        src.start()


def test_file_source_downmixes_stereo(tmp_path):
    """Stereo input averaged to mono — caller doesn't have to know."""
    wav_path = tmp_path / "stereo.wav"
    samples = np.array([[1.0, -1.0]] * 100, dtype=np.float32)  # silence after sum
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes((samples * 32767).clip(-32768, 32767).astype(np.int16).tobytes())

    src = FileSource(path=wav_path, chunk_samples=100)
    chunks = list(src)
    assert len(chunks) == 1
    np.testing.assert_allclose(chunks[0], np.zeros(100), atol=1e-3)


# ── MicSource laziness (does not require a real mic) ───────────────────────


def test_mic_source_does_not_import_sounddevice_until_start():
    """The core must import on a host without sounddevice — confirm.

    We don't try to actually start a stream here; we just verify the
    constructor doesn't trigger the import. Doing so is the whole
    point of Strategy D (voice variant).
    """
    import sys

    # Pretend sounddevice is missing for the constructor call.
    sentinel = sys.modules.pop("sounddevice", None)
    try:
        from newton.voice.audio_source import MicSource

        src = MicSource(sample_rate=16000, chunk_samples=512)
        # Construction succeeded without sounddevice in sys.modules.
        assert src.sample_rate == 16000
        assert "sounddevice" not in sys.modules
    finally:
        if sentinel is not None:
            sys.modules["sounddevice"] = sentinel
