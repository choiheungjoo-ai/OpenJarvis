"""Proactive engine configuration — ``config/proactive.yaml``.

Loads the threshold rule list and the cooldown window. Mirrors the
``newton.system_config`` pattern: optional file, sensible built-in
defaults, optional ``proactive.local.yaml`` overlay for sir-only tuning.

Why a separate file from ``newton.yaml``?
    ``newton.yaml`` holds infrastructure (embedding backend, vault
    layout) that affects every block. ``proactive.yaml`` is the
    user-tuning surface for *this* block — a different audience and a
    different change cadence. Keeping them apart matches how
    ``personas.yaml`` already lives next to ``newton.yaml``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────


class ThresholdRule(BaseModel):
    """One threshold rule.

    The ``kind`` is the storage-only prefix used to identify the rule in
    ``proactive_notifications.notification_text`` for cooldown lookups.
    It must never reach the user — see ``newton.proactive.alerts.display_text``.
    """

    kind: str = Field(min_length=1)
    metric_type: str
    op: Literal[">", "<"]
    value: float
    text: str
    dormant: bool = False

    @field_validator("kind")
    @classmethod
    def _kind_is_identifier(cls, v: str) -> str:
        # Anchors the regex used by display_text(): [a-z0-9_]+ only.
        if not all(c.islower() or c.isdigit() or c == "_" for c in v):
            raise ValueError(
                f"kind must be lowercase letters / digits / underscores: {v!r}"
            )
        return v


class ProactiveConfig(BaseModel):
    """Top-level proactive engine configuration."""

    thresholds: list[ThresholdRule] = Field(default_factory=list)
    cooldown_minutes: int = 15

    @field_validator("cooldown_minutes")
    @classmethod
    def _cooldown_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("cooldown_minutes must be >= 0")
        return v


class ProactiveConfigError(RuntimeError):
    """Raised when ``proactive.yaml`` exists but fails to parse / validate."""


# ─────────────────────────────────────────────────────────────────────────────
# Path resolution (mirrors newton.system_config)
# ─────────────────────────────────────────────────────────────────────────────


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _config_dir() -> Path:
    env = os.environ.get("NEWTON_CONFIG_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return _project_root() / "config"


def _config_paths() -> tuple[Path, Path]:
    base = _config_dir() / "proactive.yaml"
    local = _config_dir() / "proactive.local.yaml"
    return base, local


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def _builtin_defaults() -> ProactiveConfig:
    """The hard-coded fallback if no file is found.

    Kept minimal — the *real* defaults live in ``config/proactive.yaml``.
    This only exists so a fresh checkout where the file is missing still
    produces a working (if conservative) checker.
    """
    return ProactiveConfig(
        thresholds=[
            ThresholdRule(
                kind="cpu_high",
                metric_type="cpu",
                op=">",
                value=90.0,
                text="Sir, CPU at {value:.0f}%.",
            ),
            ThresholdRule(
                kind="battery_low",
                metric_type="battery",
                op="<",
                value=20.0,
                text="Sir, battery at {value:.0f}%.",
            ),
        ],
        cooldown_minutes=15,
    )


def load_proactive_config() -> ProactiveConfig:
    """Load ``proactive.yaml`` (+ ``.local.yaml`` overlay) or return defaults."""
    base, local = _config_paths()

    if not base.exists() and not local.exists():
        return _builtin_defaults()

    merged: dict[str, Any] = {}
    if base.exists():
        merged.update(_load_yaml(base))
    if local.exists():
        merged.update(_load_yaml(local))

    try:
        return ProactiveConfig.model_validate(merged)
    except Exception as e:  # noqa: BLE001
        raise ProactiveConfigError(f"failed to parse proactive.yaml: {e}") from e


__all__ = [
    "ProactiveConfig",
    "ProactiveConfigError",
    "ThresholdRule",
    "load_proactive_config",
]
