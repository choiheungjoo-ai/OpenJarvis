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
from typing import Any, Literal

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


CLAP_MODES = ("clap_shared", "clap_sir_only", "clap_off")


class ClapConfig(BaseModel):
    """2-clap-in-sequence trigger.

    Detects two distinct energy peaks within a configurable window.
    Single peaks (door slam, single applause) don't fire — the
    pair-in-window rule keeps false positives down without needing a
    model. The doc mentions an openWakeWord-trained clap classifier;
    the energy-peak approach is shipped first because it has no
    extra dep and is deterministic in tests.

    Permission modes (block-5 §5.12) — who is allowed to wake Newton
    via clap:

        * ``clap_shared`` (default) — any registered user.
        * ``clap_sir_only`` — clap is provisional; the next utterance
          must Voice-ID as ``privileged_user_id`` to be confirmed.
        * ``clap_off`` — clap is disabled; wake word only.
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
    # Permission mode (see class docstring). String-typed (rather than
    # an Enum) so YAML overrides stay human-readable.
    mode: str = "clap_shared"
    # User_id that ``clap_sir_only`` confirms against. Default ``sir``
    # mirrors the seeded owner; gf is never the privileged speaker.
    privileged_user_id: str = "sir"

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

    @field_validator("mode")
    @classmethod
    def _known_mode(cls, v: str) -> str:
        if v not in CLAP_MODES:
            raise ValueError(f"mode must be one of {CLAP_MODES!r}, got {v!r}")
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
    """One persona+language → engine+sample binding (step 5.5).

    Two synthesis modes are supported:

    * Custom voice — the engine's fine-tuned ``speaker`` is set and
      no reference clip is needed (JARVIS via ``generate_custom_voice``).
    * Clone — ``voice_reference`` points at a sample WAV and ``ref_text``
      holds its exact transcript (Qwen3-TTS ``generate_voice_clone``
      requires both).

    Both fields are optional; the engine itself decides which mode it
    runs in based on construction-time configuration. The router just
    threads the values through.
    """

    persona: str
    # ``any`` is a wildcard matched by the router's resolve().
    language: str = "any"
    engine: str
    # Path relative to ``tts.voice_root``. May not exist yet (samples
    # land in step 5.4); the router passes the path through anyway.
    voice_reference: str | None = None
    # Fine-tuned speaker name for custom-voice engines. Informational at
    # the route level (the engine instance carries the actual mode);
    # surfaced here so config-aware callers can branch without inspecting
    # engine internals.
    speaker: str | None = None
    # Exact transcript of ``voice_reference``. REQUIRED by Qwen3-TTS
    # clone mode; ignored by custom-voice and by engines that don't use
    # a transcript.
    ref_text: str | None = None


class TTSConfig(BaseModel):
    """Voice routing + sample-root for the TTS layer (step 5.5).

    ``backend`` selects how the ``qwen3_tts_*`` engines run:

    * ``remote`` (default) — talk to the ``newton-tts`` Docker service
      over HTTP (``newton/voice/tts/http_backend.py``). Strategy D: the
      Newton process stays torch-free; GPU work lives in the container.
    * ``local`` — construct the in-process :class:`Qwen3TTS` adapter
      (needs ``qwen-tts`` + GPU). Used by offline dev and unit tests.

    ``url`` / ``timeout_s`` apply only to ``remote``; defaults match the
    service deployed by ``deploy/docker/tts/compose.yaml``.
    """

    voice_root: str = "data/voices"
    backend: Literal["local", "remote"] = "remote"
    url: str = "http://localhost:8081"
    timeout_s: float = 60.0
    routes: list[TTSRouteConfig] = Field(
        default_factory=lambda: [
            # Butler — Base model clone. ref_text must be filled in
            # voice.local.yaml once the donor sample is recorded.
            TTSRouteConfig(
                persona="butler",
                language="any",
                engine="qwen3_tts_base",
                voice_reference="butler/ko-001.wav",
            ),
            # JARVIS — fine-tuned custom-voice model. Same engine for
            # ko + en; the model handles both languages.
            TTSRouteConfig(
                persona="jarvis",
                language="ko",
                engine="qwen3_tts_jarvis",
                speaker="jarvis",
            ),
            TTSRouteConfig(
                persona="jarvis",
                language="en",
                engine="qwen3_tts_jarvis",
                speaker="jarvis",
            ),
            # Friday — Base model clone. ref_text per language goes in
            # voice.local.yaml.
            TTSRouteConfig(
                persona="friday",
                language="ko",
                engine="qwen3_tts_base",
                voice_reference="friday/ko-001.wav",
            ),
            TTSRouteConfig(
                persona="friday",
                language="en",
                engine="qwen3_tts_base",
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
    "CLAP_MODES",
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
