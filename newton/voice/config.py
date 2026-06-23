"""Voice layer configuration — ``config/voice.yaml``.

Separate from ``proactive.yaml`` and ``newton.yaml``: voice has its
own user-facing tuning surface (sample rate, VAD threshold, mic
device) that nothing else cares about.

Resolution mirrors ``newton.system_config``:
    1. ``NEWTON_CONFIG_DIR`` env var, if set
    2. otherwise ``<project_root>/config``

The file is optional — defaults apply when absent. ``voice.local.yaml``
overlays sir-only overrides (gitignored).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class AudioConfig(BaseModel):
    """Mic / file / mock source defaults."""

    # Silero VAD expects 16 kHz mono. Whisper expects 16 kHz too.
    sample_rate: int = 16000
    # Silero's per-call chunk size at 16 kHz is 512 samples (~32 ms).
    # Smaller chunks tighten latency; larger reduce CPU.
    chunk_samples: int = 512
    # sounddevice device name or index. ``None`` → default input.
    mic_device: str | int | None = None

    @field_validator("sample_rate", "chunk_samples")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be > 0")
        return v


class VADConfig(BaseModel):
    """Silero VAD knobs."""

    # Probability threshold at which a chunk counts as speech.
    threshold: float = 0.5
    # Minimum consecutive speech chunks before we report "speech started"
    # downstream. Single-chunk blips (mouse clicks, keyboard noise) are
    # swallowed by this.
    min_speech_chunks: int = 3
    # Silence chunks before "speech ended". Wider = less choppy
    # turn-taking; narrower = lower latency.
    min_silence_chunks: int = 15

    @field_validator("threshold")
    @classmethod
    def _threshold_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("threshold must be in [0, 1]")
        return v

    @field_validator("min_speech_chunks", "min_silence_chunks")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be > 0")
        return v


class ClapConfig(BaseModel):
    """2-clap-in-sequence trigger.

    Detects two distinct energy peaks within a configurable window.
    Single peaks (door slam, single applause) don't fire — the
    pair-in-window rule keeps false positives down without needing a
    model. The doc mentions an openWakeWord-trained clap classifier;
    the energy-peak approach is shipped first because it has no
    extra dep and is deterministic in tests.
    """

    enabled: bool = True
    # Per-chunk RMS above which a chunk counts as a "peak candidate".
    peak_threshold: float = 0.15
    # Minimum gap (ms) between the two peaks. Anything tighter is one
    # clap that bounced off the ceiling.
    min_gap_ms: int = 90
    # Maximum gap (ms) between the two peaks. Beyond this, we consider
    # the first peak a single noise event and reset.
    max_gap_ms: int = 500

    @field_validator("peak_threshold")
    @classmethod
    def _threshold_range(cls, v: float) -> float:
        if not 0.0 < v <= 1.0:
            raise ValueError("peak_threshold must be in (0, 1]")
        return v

    @field_validator("min_gap_ms", "max_gap_ms")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be > 0")
        return v


class WakeConfig(BaseModel):
    """openWakeWord wrapper settings."""

    # Names sir will say. Each maps 1:1 to an openWakeWord model that
    # the lazy loader fetches. The persona-naming routing (block 3)
    # interprets which of these wake words also activates a persona.
    enabled: bool = True
    wake_words: list[str] = Field(
        default_factory=lambda: ["newton", "jarvis", "friday", "butler"]
    )
    # Score above which openWakeWord's predict() output is treated as
    # a match. 0.5 is the library's documented default.
    score_threshold: float = 0.5

    @field_validator("score_threshold")
    @classmethod
    def _threshold_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("score_threshold must be in [0, 1]")
        return v


class Stage1Config(BaseModel):
    """Top-level Stage-1 activation knobs (wake word OR clap)."""

    wake: WakeConfig = Field(default_factory=WakeConfig)
    clap: ClapConfig = Field(default_factory=ClapConfig)


class TTSRouteConfig(BaseModel):
    """One persona+language → engine+sample binding (step 5.5)."""

    persona: str
    # ``any`` is a wildcard matched by the router's resolve().
    language: str = "any"
    engine: str
    # Path relative to ``tts.voice_root``. May not exist yet (samples
    # land in step 5.4); the router passes the path through anyway.
    voice_reference: str | None = None


class TTSConfig(BaseModel):
    """Voice routing + sample-root for the TTS layer (step 5.5)."""

    voice_root: str = "data/voices"
    routes: list[TTSRouteConfig] = Field(
        default_factory=lambda: [
            TTSRouteConfig(
                persona="butler",
                language="any",
                engine="qwen3_tts_0.6b",
                voice_reference="butler/ko-001.wav",
            ),
            TTSRouteConfig(
                persona="jarvis",
                language="ko",
                engine="qwen3_tts_1.7b",
                voice_reference="jarvis/ko-001.wav",
            ),
            TTSRouteConfig(
                persona="jarvis",
                language="en",
                engine="chatterbox",
                voice_reference="jarvis/chatterbox-reference.wav",
            ),
            TTSRouteConfig(
                persona="friday",
                language="ko",
                engine="qwen3_tts_1.7b",
                voice_reference="friday/ko-001.wav",
            ),
            TTSRouteConfig(
                persona="friday",
                language="en",
                engine="qwen3_tts_1.7b",
                voice_reference="friday/en-001.wav",
            ),
        ]
    )


class SessionLockConfig(BaseModel):
    """Multi-speaker session-lock policy (step 5.10)."""

    # Seconds of silence from the locked user before the session
    # unlocks. The default matches the design doc (voice.md §2.8).
    timeout_seconds: int = 30

    @field_validator("timeout_seconds")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("timeout_seconds must be > 0")
        return v


class VoiceIdConfig(BaseModel):
    """Voice ID enrollment + recognition (step 5.9).

    Resemblyzer is an optional install (``voice-id`` extra) so default
    install stays torch-free. The backend lazy-imports its model on
    first use; the ``fake`` backend exists for tests and for dev hosts
    without the extra.
    """

    # ``resemblyzer`` or ``fake``. Tests flip this to ``fake`` so
    # nothing imports torch.
    backend: str = "resemblyzer"
    # Resemblyzer runs cheaply on CPU; CPU also avoids the local
    # sm_120 CUDA toolchain. Pass through to ``VoiceEncoder``.
    device: str = "cpu"
    # Cosine similarity above which a match is accepted by
    # ``VoiceIdService.identify``.
    threshold: float = 0.75
    # Resemblyzer's expected mono sample rate. Stored here so callers
    # can pass it through without a literal.
    sample_rate: int = 16000

    @field_validator("threshold")
    @classmethod
    def _threshold_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("threshold must be in [0, 1]")
        return v

    @field_validator("sample_rate")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("sample_rate must be > 0")
        return v


class VoiceConfig(BaseModel):
    """Top-level voice configuration."""

    audio: AudioConfig = Field(default_factory=AudioConfig)
    vad: VADConfig = Field(default_factory=VADConfig)
    stage1: Stage1Config = Field(default_factory=Stage1Config)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    session_lock: SessionLockConfig = Field(default_factory=SessionLockConfig)
    voice_id: VoiceIdConfig = Field(default_factory=VoiceIdConfig)


class VoiceConfigError(RuntimeError):
    """Raised when ``voice.yaml`` exists but fails to parse / validate."""


# ─────────────────────────────────────────────────────────────────────────────
# Path resolution (mirrors newton.system_config / proactive.config)
# ─────────────────────────────────────────────────────────────────────────────


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _config_dir() -> Path:
    env = os.environ.get("NEWTON_CONFIG_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return _project_root() / "config"


def _config_paths() -> tuple[Path, Path]:
    return _config_dir() / "voice.yaml", _config_dir() / "voice.local.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def load_voice_config() -> VoiceConfig:
    """Load ``voice.yaml`` (+ ``.local.yaml`` overlay) or return defaults."""
    base, local = _config_paths()
    if not base.exists() and not local.exists():
        return VoiceConfig()

    merged: dict[str, Any] = {}
    if base.exists():
        merged.update(_load_yaml(base))
    if local.exists():
        merged.update(_load_yaml(local))

    try:
        return VoiceConfig.model_validate(merged)
    except Exception as e:  # noqa: BLE001
        raise VoiceConfigError(f"failed to parse voice.yaml: {e}") from e


__all__ = [
    "AudioConfig",
    "ClapConfig",
    "SessionLockConfig",
    "Stage1Config",
    "TTSConfig",
    "TTSRouteConfig",
    "VADConfig",
    "VoiceConfig",
    "VoiceConfigError",
    "VoiceIdConfig",
    "WakeConfig",
    "load_voice_config",
]
