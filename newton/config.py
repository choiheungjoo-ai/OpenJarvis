"""Newton config loader.

Reads ``config/personas.yaml`` (and optional ``personas.local.yaml`` override)
into validated Pydantic models.

Public API
----------
    load_config()                       → NewtonConfig
    render_personality(persona, owner)  → str

Resolution order for the config directory:
    1. ``NEWTON_CONFIG_DIR`` environment variable, if set
    2. ``<project_root>/config``           (auto-detected from this file)

Files loaded (in order, merged):
    1. ``personas.yaml``         (required, tracked in git)
    2. ``personas.local.yaml``   (optional, gitignored, sir-only overrides)

Block-1 scope: only ``personas.yaml`` is loaded.  DB-backed config arrives
in block 3+.  This module deliberately does no I/O beyond reading these
two files.

Placeholder substitution
------------------------
``personality`` strings may contain ``${OWNER_DISPLAY_NAME}``.  These are
**not** substituted at load time — the loader keeps the raw template.
Substitution happens via :func:`render_personality` when the LLM call is
actually made, with the user's display name from the ``users`` table.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from string import Template
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models — schema for personas.yaml
# ─────────────────────────────────────────────────────────────────────────────


class VoiceConfig(BaseModel):
    """One TTS configuration (engine + optional voice clone embedding)."""

    model_config = ConfigDict(extra="forbid")

    engine: str = Field(..., description="TTS engine name, e.g. 'qwen3-tts-1.7b'.")
    embedding_path: str | None = Field(
        default=None,
        description="Path to a cloned-voice embedding file. Filled in block 4.",
    )


# JARVIS uses {ko: VoiceConfig, en: VoiceConfig} so we model that as a dict.
# Butler/Friday use a single VoiceConfig.  We accept either shape.
PersonaVoice = VoiceConfig | dict[str, VoiceConfig]


class Persona(BaseModel):
    """One persona definition."""

    model_config = ConfigDict(extra="forbid")

    display_name: str
    is_public: bool = False
    is_default: bool = False
    owner: str | None = Field(
        default=None,
        description=(
            "User ID of the owner. ``None`` = public persona (e.g. butler). "
            "References ``users.user_id`` once the DB is online (block 1.6)."
        ),
    )
    voice: PersonaVoice
    personality: str = Field(
        ..., description="System prompt; may contain ${OWNER_DISPLAY_NAME}."
    )
    color: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")

    @model_validator(mode="after")
    def _owner_consistency(self) -> Persona:
        # A public persona must not have an owner; a private one must.
        if self.is_public and self.owner is not None:
            raise ValueError("public personas must have owner=null")
        if not self.is_public and self.owner is None:
            raise ValueError("private personas must declare an owner")
        return self


class RetryProfile(BaseModel):
    """One identity retry profile (strict / normal / relaxed)."""

    model_config = ConfigDict(extra="forbid")

    max_retries: int = Field(..., ge=1, le=20)
    threshold: float = Field(..., ge=0.0, le=1.0)


class FallbackPolicy(BaseModel):
    """Auth fallback policy when voice/face fail."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    methods: list[Literal["pin", "passphrase"]] = Field(default_factory=list)
    after_voice_failure: bool = True
    after_face_failure: bool = True


class IdentityPolicy(BaseModel):
    """How Newton handles speaker identification."""

    model_config = ConfigDict(extra="forbid")

    guest_mode_enabled: bool = False
    retry_profiles: dict[str, RetryProfile]
    active_profile: str
    fallback: FallbackPolicy

    @model_validator(mode="after")
    def _active_profile_exists(self) -> IdentityPolicy:
        if self.active_profile not in self.retry_profiles:
            raise ValueError(
                f"active_profile={self.active_profile!r} not in "
                f"retry_profiles {sorted(self.retry_profiles)}"
            )
        return self


class NewtonConfig(BaseModel):
    """Top-level config object."""

    model_config = ConfigDict(extra="forbid")

    personas: dict[str, Persona]
    identity: IdentityPolicy

    @model_validator(mode="after")
    def _exactly_one_default(self) -> NewtonConfig:
        defaults = [pid for pid, p in self.personas.items() if p.is_default]
        if len(defaults) != 1:
            raise ValueError(
                f"exactly one persona must have is_default=true; "
                f"got {len(defaults)}: {defaults}"
            )
        return self


# ─────────────────────────────────────────────────────────────────────────────
# Path resolution
# ─────────────────────────────────────────────────────────────────────────────


def _project_root() -> Path:
    # newton/config.py  →  newton/  →  <project root>
    return Path(__file__).resolve().parent.parent


def _config_dir() -> Path:
    env = os.environ.get("NEWTON_CONFIG_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return _project_root() / "config"


# ─────────────────────────────────────────────────────────────────────────────
# YAML loading + deep-merge for local override
# ─────────────────────────────────────────────────────────────────────────────


def _deep_merge(base: dict[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    """Recursive dict merge.  ``over`` wins.  Non-dict values are replaced."""
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(
            f"{path}: expected top-level mapping, got {type(data).__name__}"
        )
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


class ConfigError(RuntimeError):
    """Raised when config files are missing or fail validation."""


@cache
def load_config() -> NewtonConfig:
    """Load (and cache) Newton's configuration.

    Raises:
        ConfigError: if ``personas.yaml`` is missing or validation fails.
    """
    cfg_dir = _config_dir()
    base_path = cfg_dir / "personas.yaml"
    local_path = cfg_dir / "personas.local.yaml"

    if not base_path.is_file():
        raise ConfigError(
            f"personas.yaml not found at {base_path}.\n"
            f"Set NEWTON_CONFIG_DIR or place the file at the expected location."
        )

    try:
        data = _load_yaml(base_path)
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML parse error in {base_path}: {e}") from e

    if local_path.is_file():
        try:
            data = _deep_merge(data, _load_yaml(local_path))
        except yaml.YAMLError as e:
            raise ConfigError(f"YAML parse error in {local_path}: {e}") from e

    try:
        return NewtonConfig.model_validate(data)
    except Exception as e:  # pydantic ValidationError or our model_validator
        raise ConfigError(f"config validation failed:\n{e}") from e


def render_personality(persona: Persona, owner_display_name: str | None) -> str:
    """Substitute ``${OWNER_DISPLAY_NAME}`` in a persona's personality string.

    For public personas (owner=None), the placeholder is left untouched —
    the caller should not pass such personas to the LLM with a name.
    ``safe_substitute`` is used so unknown placeholders never raise.
    """
    if owner_display_name is None:
        return persona.personality
    return Template(persona.personality).safe_substitute(
        OWNER_DISPLAY_NAME=owner_display_name
    )


__all__ = [
    "ConfigError",
    "FallbackPolicy",
    "IdentityPolicy",
    "NewtonConfig",
    "Persona",
    "RetryProfile",
    "VoiceConfig",
    "load_config",
    "render_personality",
]
