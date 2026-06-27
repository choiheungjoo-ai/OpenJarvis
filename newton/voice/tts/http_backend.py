"""HTTP backend for the ``newton-tts`` Docker service.

Mirrors the TEI pattern in ``newton/vault/embedding_backends/tei.py``:
the Newton core process stays torch-free; the GPU work (Qwen3-TTS
inference) runs inside the container. The contract is fixed by
``deploy/docker/tts/server.py``:

    GET  /health      -> 200 ``{"ok": true}``
    POST /synthesize  body:
        ``{text, language: "korean"|"english", mode: "custom_voice"|"clone",
           speaker?, ref_audio_b64?, ref_text?}``
        -> ``{audio_b64: str (base64 wav), sample_rate: int}``

* custom_voice → JARVIS fine-tuned (``speaker="jarvis"``), no reference.
* clone        → Base model, needs ``ref_audio_b64`` + ``ref_text``.

The router's short language codes (``"ko"`` / ``"en"``) are translated
to the service's full-name vocabulary via the existing
:func:`newton.voice.tts.qwen3._to_full_language`; the rule lives in one
place.
"""

from __future__ import annotations

import base64
import io
import logging
import wave
from pathlib import Path

import httpx
import numpy as np

from newton.voice.tts.base import TTS, TTSResult
from newton.voice.tts.qwen3 import _to_full_language

log = logging.getLogger(__name__)

#: Default URL of the newton-tts service. Match ``deploy/docker/tts/``.
DEFAULT_TTS_URL = "http://localhost:8081"
#: Default per-request timeout. Synthesis on a warm GPU is ~1-3 s for short
#: utterances; the cushion absorbs cold starts and longer phrases.
DEFAULT_TTS_TIMEOUT_S = 60.0


class TTSBackendError(RuntimeError):
    """Raised when the remote TTS service rejects a request or is unreachable.

    Subclasses :class:`RuntimeError` so the block-5 fallback chain
    (:mod:`newton.voice.tts.fallback`) catches it like any other engine
    failure and advances to the next tier.
    """


class RemoteQwen3TTS(TTS):
    """Qwen3-TTS via the ``newton-tts`` HTTP service.

    One instance per engine identity (``qwen3_tts_jarvis`` vs
    ``qwen3_tts_base``). Custom-voice vs clone mode is selected by
    construction — same rule as the in-process :class:`Qwen3TTS`:

    * ``speaker`` set → ``mode="custom_voice"`` (no reference clip).
    * ``speaker`` None + caller passes ``voice_reference`` + ``ref_text``
      → ``mode="clone"``.
    """

    name = "qwen3_tts_remote"

    def __init__(
        self,
        *,
        name: str = "qwen3_tts_remote",
        speaker: str | None = None,
        url: str = DEFAULT_TTS_URL,
        timeout_s: float = DEFAULT_TTS_TIMEOUT_S,
    ) -> None:
        # ``name`` carries the engine identity used by the router cache key
        # and the fallback log — keep it distinct for the two flavours so a
        # single router can host both.
        self.name = name
        self.speaker = speaker
        self._url = url.rstrip("/")
        self._timeout = timeout_s

    def synthesize(
        self,
        text: str,
        *,
        language: str | None = None,
        voice_reference: Path | str | None = None,
        ref_text: str | None = None,
    ) -> TTSResult:
        if not text.strip():
            raise ValueError("text must be non-empty")
        # Translate the router's short codes at the adapter boundary so the
        # mapping rule lives in one place (qwen3.py).
        full_language = _to_full_language(language)
        if full_language is None:
            raise ValueError(
                "RemoteQwen3TTS.synthesize requires language (e.g. 'ko' or 'en')"
            )

        body = self._build_body(text, full_language, voice_reference, ref_text)

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(f"{self._url}/synthesize", json=body)
        except httpx.HTTPError as e:
            raise TTSBackendError(
                f"newton-tts request failed at {self._url}: {e}"
            ) from e

        if resp.status_code != 200:
            raise TTSBackendError(
                f"newton-tts returned HTTP {resp.status_code}: {resp.text[:200]}"
            )

        payload = resp.json()
        audio_b64 = payload.get("audio_b64")
        sr = payload.get("sample_rate")
        if not audio_b64 or sr is None:
            raise TTSBackendError(
                f"newton-tts response missing audio_b64/sample_rate: {payload!r}"
            )
        audio = _decode_wav_b64(audio_b64)
        return TTSResult(audio=audio, sample_rate=int(sr))

    def health(self) -> bool:
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(f"{self._url}/health")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    def _build_body(
        self,
        text: str,
        full_language: str,
        voice_reference: Path | str | None,
        ref_text: str | None,
    ) -> dict[str, object]:
        if self.speaker is not None:
            # Custom-voice: fine-tuned speaker baked into the model. Any
            # caller-supplied reference is silently ignored — the mode is
            # decided at construction time, same as in-process Qwen3TTS.
            return {
                "text": text,
                "language": full_language,
                "mode": "custom_voice",
                "speaker": self.speaker,
            }
        if voice_reference is None:
            raise ValueError(
                "RemoteQwen3TTS.synthesize requires either a configured speaker "
                "(custom-voice mode) or a voice_reference + ref_text pair "
                "(clone mode)"
            )
        # Clone: ref_text is required by the server. Mismatched / missing
        # transcripts yield garbled output, so fail loud at the boundary.
        if not ref_text or not ref_text.strip():
            raise ValueError(
                "RemoteQwen3TTS clone mode needs ref_text matching voice_reference;"
                f" got voice_reference={voice_reference!r} ref_text={ref_text!r}"
            )
        ref_path = Path(voice_reference)
        try:
            ref_bytes = ref_path.read_bytes()
        except OSError as e:
            raise TTSBackendError(
                f"failed to read voice_reference {ref_path}: {e}"
            ) from e
        return {
            "text": text,
            "language": full_language,
            "mode": "clone",
            "ref_audio_b64": base64.b64encode(ref_bytes).decode("ascii"),
            "ref_text": ref_text,
        }


def _decode_wav_b64(audio_b64: str) -> np.ndarray:
    """Decode a base64-encoded PCM WAV into a mono float32 ndarray.

    The service writes WAVs via ``soundfile.write(..., format="WAV")``;
    the libsndfile default subtype for WAV is 16-bit PCM (``PCM_16``).
    We also handle 32-bit PCM as a safety net should the service ever
    switch subtypes.
    """
    try:
        wav_bytes = base64.b64decode(audio_b64)
    except (ValueError, TypeError) as e:
        raise TTSBackendError(f"newton-tts returned undecodable audio_b64: {e}") from e
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            nchan = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())
    except wave.Error as e:
        raise TTSBackendError(f"newton-tts returned malformed wav: {e}") from e

    if sampwidth == 2:
        pcm = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        pcm = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise TTSBackendError(
            f"newton-tts returned unsupported WAV sample width {sampwidth} bytes"
        )
    if nchan > 1:
        pcm = pcm.reshape(-1, nchan).mean(axis=1)
    return pcm.astype(np.float32, copy=False)


__all__ = [
    "DEFAULT_TTS_TIMEOUT_S",
    "DEFAULT_TTS_URL",
    "RemoteQwen3TTS",
    "TTSBackendError",
]
