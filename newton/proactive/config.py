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


class SequencePatternConfig(BaseModel):
    """Sequence-pattern-specific knobs (currently just the window)."""

    default_window_seconds: int = 600

    @field_validator("default_window_seconds")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("default_window_seconds must be > 0")
        return v


class PatternsConfig(BaseModel):
    """Pattern recognition + confidence scoring knobs (block 4 step 4.3).

    The confidence model is:

        confidence = consistency × volume × recency × (1 - penalty)

    Every coefficient here is observable, not magical. Tune in the
    YAML; the scorer reads them at call time.
    """

    # How far back the learner looks. Observations older than this are
    # invisible to both the numerator and the denominator, so they
    # naturally fall off rather than being penalised twice (numerator
    # drop + recency decay).
    observation_window_days: int = 28

    # Pre-filter: a pattern fewer than this many occurrences shouldn't
    # be allowed to score at all. The doc's ``observed_count >= 3``
    # gate, configurable here.
    min_occurrences_floor: int = 3

    # Pre-filter: denominator floor. If we've only observed N=2
    # opportunities (Tuesdays, vault_searches, …), consistency is too
    # noisy to use — return 0.0 confidence rather than a number we'd
    # have to caveat.
    min_opportunities: int = 4

    # Volume factor saturates at this many occurrences. So
    # ``min(1, occurrences / min_confident_samples)`` — a 3-of-3
    # pattern at 100% consistency only hits the ceiling at this many
    # observations.
    min_confident_samples: int = 10

    # Recency decay e^(-days_since_last_seen / half_life_days).
    # 30 ⇒ a pattern not seen for 30 days decays to ≈0.37.
    half_life_days: float = 30.0

    # Until ``users.timezone`` lands (likely 4.5 quiet hours), use one
    # global timezone for weekday/hour bucketing. SQLite stores naive
    # UTC; the learner shifts through this offset before bucketing.
    pattern_timezone: str = "Asia/Seoul"

    sequence: SequencePatternConfig = Field(default_factory=SequencePatternConfig)

    @field_validator(
        "observation_window_days",
        "min_occurrences_floor",
        "min_opportunities",
        "min_confident_samples",
    )
    @classmethod
    def _positive_int(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be > 0")
        return v

    @field_validator("half_life_days")
    @classmethod
    def _positive_half_life(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("half_life_days must be > 0")
        return v


class ModeThresholds(BaseModel):
    """Per-mode score threshold above which a prediction is allowed to fire.

    The anticipation engine compares ``confidence × relevance`` against
    ``thresholds[mode]``. ``off`` uses a value > 1.0 so nothing ever
    crosses — encoding "never fire" in the same comparison without a
    separate code path.
    """

    off: float = 1.01
    minimal: float = 0.9
    smart: float = 0.7
    aggressive: float = 0.5

    @field_validator("off", "minimal", "smart", "aggressive")
    @classmethod
    def _threshold_range(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError("mode thresholds must be >= 0")
        return v


class AnticipationConfig(BaseModel):
    """Knobs for the anticipation engine (step 4.4)."""

    # Default proactive mode applied when ``users.proactive_mode``
    # doesn't exist yet (step 4.8 adds the column). Once the column
    # lands, that value wins; this is just the fallback.
    default_mode: str = "smart"

    # Time-proximity relevance: a Gaussian centred at the predicted
    # eta with this stddev (minutes). At σ minutes from eta, relevance
    # is ≈0.61; at 2σ ≈0.13.
    relevance_sigma_minutes: float = 30.0

    # Sequence patterns: an A-event run within the last
    # ``sequence_relevance_seconds`` makes the pattern fully relevant
    # (relevance = 1.0). Beyond that, relevance is 0. Block 4.5 may
    # tighten this; the default mirrors patterns/sequence's default
    # window.
    sequence_relevance_seconds: int = 600

    # Cap on predictions returned by predict(). Keeps the CLI surface
    # readable and gives the scheduler a stable top-N to consider.
    max_results: int = 5

    thresholds: ModeThresholds = Field(default_factory=ModeThresholds)

    @field_validator("relevance_sigma_minutes")
    @classmethod
    def _positive_sigma(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("relevance_sigma_minutes must be > 0")
        return v

    @field_validator("sequence_relevance_seconds", "max_results")
    @classmethod
    def _positive_int(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be > 0")
        return v

    @field_validator("default_mode")
    @classmethod
    def _valid_mode(cls, v: str) -> str:
        if v not in {"off", "minimal", "smart", "aggressive"}:
            raise ValueError(
                f"default_mode must be one of off/minimal/smart/aggressive, got {v!r}"
            )
        return v


class QuietHoursConfig(BaseModel):
    """Daily window during which the scheduler stays silent.

    Wraps midnight when ``start > end`` (the typical 23:00–07:00
    case). Zero-length ``start == end`` means "never quiet".
    Timezone is the configured ``patterns.pattern_timezone`` —
    consistent with weekday bucketing.
    """

    start: str = "23:00"
    end: str = "07:00"

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        from newton.proactive.quiet_hours import parse_hhmm

        parse_hhmm(v)  # raises if malformed
        return v


class SchedulerConfig(BaseModel):
    """Knobs for the proactive notification scheduler (step 4.5)."""

    # Don't write more than this many scheduler-driven rows per tick.
    # Anticipation already caps at config.anticipation.max_results, so
    # this is a belt-and-suspenders ceiling that the scheduler itself
    # can read without reaching into the anticipation config.
    max_per_tick: int = 1

    # Per-pattern cooldown: don't schedule a second row for the same
    # pattern_id within this many minutes. Mirrors threshold-alert
    # cooldown semantics from 4.2 but keyed off trigger_pattern_id
    # instead of the [kind] prefix.
    pattern_cooldown_minutes: int = 30

    quiet_hours: QuietHoursConfig = Field(default_factory=QuietHoursConfig)

    @field_validator("max_per_tick", "pattern_cooldown_minutes")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("must be >= 0")
        return v


class ProactiveConfig(BaseModel):
    """Top-level proactive engine configuration."""

    thresholds: list[ThresholdRule] = Field(default_factory=list)
    cooldown_minutes: int = 15
    patterns: PatternsConfig = Field(default_factory=PatternsConfig)
    anticipation: AnticipationConfig = Field(default_factory=AnticipationConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)

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
    "AnticipationConfig",
    "ModeThresholds",
    "PatternsConfig",
    "ProactiveConfig",
    "ProactiveConfigError",
    "QuietHoursConfig",
    "SchedulerConfig",
    "SequencePatternConfig",
    "ThresholdRule",
    "load_proactive_config",
]
