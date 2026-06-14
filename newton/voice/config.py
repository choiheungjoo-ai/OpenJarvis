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


class VoiceConfig(BaseModel):
    """Top-level voice configuration."""

    audio: AudioConfig = Field(default_factory=AudioConfig)
    vad: VADConfig = Field(default_factory=VADConfig)
    stage1: Stage1Config = Field(default_factory=Stage1Config)


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
    "Stage1Config",
    "VADConfig",
    "VoiceConfig",
    "VoiceConfigError",
    "WakeConfig",
    "load_voice_config",
]
