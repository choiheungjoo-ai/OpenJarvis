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


class VoiceConfig(BaseModel):
    """Top-level voice configuration."""

    audio: AudioConfig = Field(default_factory=AudioConfig)
    vad: VADConfig = Field(default_factory=VADConfig)


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
    "VADConfig",
    "VoiceConfig",
    "VoiceConfigError",
    "load_voice_config",
]
