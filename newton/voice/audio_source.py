"""Audio source abstraction for the voice stack.

The interface is deliberately tiny:

    start()  →  open the underlying source (mic stream, file handle, ...)
    read()   →  return one chunk of mono float32 samples, or ``None`` at EOF
    close()  →  shut down

This lets every downstream stage (VAD, wake-word, STT) take an
``AudioSource`` without caring whether the bytes come from a real mic
(:class:`MicSource`), a WAV file (:class:`FileSource`), or a Python
list (:class:`ListSource`, used by tests).

The mic source lazy-imports ``sounddevice`` at :meth:`start`. Tests
never trigger that — they use ``ListSource``. The core stays importable
on machines without sounddevice or a working USB mic.

WSL2 mic note
-------------
``sounddevice`` on WSL2 needs a Windows-side PulseAudio bridge. The
setup steps live in ``docs/newton/voice-audio-setup.md``. Tests
deliberately don't depend on a working mic.
"""

from __future__ import annotations

import queue
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


class AudioSource(ABC):
    """One source of mono float32 audio at a known sample rate."""

    sample_rate: int
    chunk_samples: int

    @abstractmethod
    def start(self) -> None:
        """Open the underlying source. Idempotent."""

    @abstractmethod
    def read(self) -> np.ndarray | None:
        """Return one chunk (mono float32) or ``None`` if no more data."""

    @abstractmethod
    def close(self) -> None:
        """Shut down. Idempotent — safe to call without ``start``."""

    def __iter__(self):
        """Yield chunks until exhausted. Calls ``start`` / ``close`` around it."""
        self.start()
        try:
            while True:
                chunk = self.read()
                if chunk is None:
                    return
                yield chunk
        finally:
            self.close()


# ─────────────────────────────────────────────────────────────────────────────
# Test / in-memory source
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ListSource(AudioSource):
    """In-memory source — feed it a pre-recorded list of chunks.

    Used by every test that touches audio plumbing. No I/O, no lazy
    imports. The first chunk's ``dtype`` should be ``float32``; we
    don't convert silently.
    """

    chunks: list[np.ndarray] = field(default_factory=list)
    sample_rate: int = 16000
    chunk_samples: int = 512
    _pos: int = 0
    _started: bool = False

    def start(self) -> None:
        self._pos = 0
        self._started = True

    def read(self) -> np.ndarray | None:
        if not self._started or self._pos >= len(self.chunks):
            return None
        chunk = self.chunks[self._pos]
        self._pos += 1
        return chunk

    def close(self) -> None:
        self._started = False


# ─────────────────────────────────────────────────────────────────────────────
# WAV file source — uses only the stdlib ``wave`` module + numpy
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class FileSource(AudioSource):
    """Stream chunks out of a mono PCM WAV file.

    Uses the stdlib ``wave`` module so no extra dep is required.
    Multi-channel WAVs are downmixed to mono. The file's sample rate
    is honoured — passing ``expected_sample_rate`` raises if it
    doesn't match (catches silent resample bugs).
    """

    path: Path | str
    chunk_samples: int = 512
    expected_sample_rate: int | None = None
    _wf: Any = None  # wave._wave_read; opaque to type-checkers
    sample_rate: int = 0  # filled in by start()
    _n_channels: int = 1
    _sample_width: int = 2  # bytes per sample (defaults to 16-bit PCM)

    def start(self) -> None:
        self._wf = wave.open(str(self.path), "rb")
        self.sample_rate = self._wf.getframerate()
        self._n_channels = self._wf.getnchannels()
        self._sample_width = self._wf.getsampwidth()
        if (
            self.expected_sample_rate is not None
            and self.sample_rate != self.expected_sample_rate
        ):
            self._wf.close()
            self._wf = None
            raise ValueError(
                f"{self.path}: sample rate {self.sample_rate} != "
                f"expected {self.expected_sample_rate}"
            )

    def read(self) -> np.ndarray | None:
        if self._wf is None:
            return None
        raw = self._wf.readframes(self.chunk_samples)
        if not raw:
            return None
        # Convert to numpy. Only 16-bit PCM is in scope for v1.
        if self._sample_width != 2:
            raise NotImplementedError(
                f"only 16-bit PCM WAV supported, got width={self._sample_width}"
            )
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if self._n_channels > 1:
            data = data.reshape(-1, self._n_channels).mean(axis=1)
        # Pad short tail so downstream chunkers see uniform sizes.
        if len(data) < self.chunk_samples:
            data = np.pad(data, (0, self.chunk_samples - len(data)))
        return data

    def close(self) -> None:
        if self._wf is not None:
            self._wf.close()
            self._wf = None


# ─────────────────────────────────────────────────────────────────────────────
# Real-mic source — lazy-imports sounddevice so the core stays light
# ─────────────────────────────────────────────────────────────────────────────


class MicSource(AudioSource):
    """USB / built-in mic via sounddevice.

    Lazy: ``sounddevice`` is imported only on :meth:`start`. The
    callback enqueues each block onto a thread-safe queue; ``read``
    pops with a small timeout. WSL2 hosts need PulseAudio; see the
    audio-setup doc.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_samples: int = 512,
        device: str | int | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.chunk_samples = chunk_samples
        self.device = device
        self._stream: Any = None
        self._queue: queue.Queue[np.ndarray] | None = None

    def start(self) -> None:
        if self._stream is not None:
            return
        import sounddevice as sd  # noqa: PLC0415 — lazy import is the whole point

        self._queue = queue.Queue()

        def _callback(indata, _frames, _time_info, status):  # noqa: ANN001
            if status:
                # Underrun / overflow — not fatal; drop the frame so
                # the queue doesn't back up to the moon.
                return
            # indata is shape (frames, channels); we want mono float32.
            mono = indata[:, 0] if indata.ndim == 2 and indata.shape[1] > 0 else indata
            self._queue.put(mono.copy().astype(np.float32).reshape(-1))

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            blocksize=self.chunk_samples,
            device=self.device,
            dtype="float32",
            callback=_callback,
        )
        self._stream.start()

    def read(self) -> np.ndarray | None:
        if self._queue is None:
            return None
        try:
            return self._queue.get(timeout=1.0)
        except queue.Empty:
            # Mic is alive but no data this second. Returning None
            # would end iteration; return a silence chunk instead so
            # downstream stages keep ticking.
            return np.zeros(self.chunk_samples, dtype=np.float32)

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._queue = None


__all__ = ["AudioSource", "FileSource", "ListSource", "MicSource"]
