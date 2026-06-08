"""System configuration — ``config/newton.yaml``.

Separate from ``personas.yaml`` (which defines personas/identity). This file
holds infrastructure settings: embedding backend, and — in later blocks —
vault paths, RAG parameters, etc. Keeping them apart lets the two files
evolve independently.

Resolution mirrors ``newton.config``:
    1. ``NEWTON_CONFIG_DIR`` env var, if set
    2. otherwise ``<project_root>/config``

The file is optional: if absent, defaults apply (so a fresh checkout works
without it). An optional ``newton.local.yaml`` overlays sir-only overrides.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────


class TeiBackendConfig(BaseModel):
    """Settings for the TEI HTTP embedding backend."""

    url: str = "http://localhost:8080"
    timeout_s: float = 30.0


class EmbeddingConfig(BaseModel):
    """Which embedding backend to use and its settings.

    ``backend`` names a registered backend (e.g. ``tei``, ``fake``).
    ``batch_size`` is an upper bound on how many texts EmbeddingService sends
    per call; None means "ask the backend / use its default".
    """

    backend: str = "tei"
    batch_size: int | None = None
    tei: TeiBackendConfig = Field(default_factory=TeiBackendConfig)


class VaultLayout(BaseModel):
    """Directory conventions inside the vault root.

    Configurable so the scanner's path-inference rules aren't hardcoded.
    """

    notes_dir: str = "notes"
    shared_dir: str = "shared"
    quarantine_dir: str = "_guest_quarantine"


class VaultConfig(BaseModel):
    """Where the vault lives and how it is laid out."""

    root: str = "data/vault"
    layout: VaultLayout = Field(default_factory=VaultLayout)


class SystemConfig(BaseModel):
    """Top-level system configuration."""

    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    vault: VaultConfig = Field(default_factory=VaultConfig)


class SystemConfigError(RuntimeError):
    """Raised when newton.yaml exists but fails to parse / validate."""


# ─────────────────────────────────────────────────────────────────────────────
# Path resolution (mirrors newton.config)
# ─────────────────────────────────────────────────────────────────────────────


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _config_dir() -> Path:
    env = os.environ.get("NEWTON_CONFIG_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return _project_root() / "config"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_system_config() -> SystemConfig:
    """Load ``newton.yaml`` (+ optional ``newton.local.yaml``).

    Missing base file is fine — defaults apply. A present-but-invalid file
    raises SystemConfigError.
    """
    cfg_dir = _config_dir()
    base_path = cfg_dir / "newton.yaml"
    local_path = cfg_dir / "newton.local.yaml"

    merged: dict[str, Any] = {}
    if base_path.exists():
        merged = _load_yaml(base_path)
    if local_path.exists():
        merged = _deep_merge(merged, _load_yaml(local_path))

    try:
        return SystemConfig(**merged)
    except Exception as e:  # pydantic ValidationError and friends
        raise SystemConfigError(f"invalid {base_path}: {e}") from e


__all__ = [
    "EmbeddingConfig",
    "VaultConfig",
    "VaultLayout",
    "SystemConfig",
    "SystemConfigError",
    "TeiBackendConfig",
    "load_system_config",
]
