"""Tests for the three-factor confidence model."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from newton.proactive.config import PatternsConfig
from newton.proactive.patterns.confidence import (
    ConfidenceBreakdown,
    score,
    score_with_breakdown,
)


def _cfg(**overrides):
    base = dict(
        observation_window_days=28,
        min_occurrences_floor=3,
        min_opportunities=4,
        min_confident_samples=10,
        half_life_days=30.0,
        pattern_timezone="Asia/Seoul",
    )
    base.update(overrides)
    return PatternsConfig(**base)


NOW = datetime(2026, 6, 14, 12, 0, 0)


# ── pre-filters ─────────────────────────────────────────────────────────────


def test_below_occurrences_floor_returns_zero():
    bd = score_with_breakdown(
        occurrences=2,
        opportunities=10,
        last_seen=NOW,
        now=NOW,
        config=_cfg(),
    )
    assert bd.score == 0.0
    assert bd.floor_passed is False
    # Factors are zeroed when the gate trips — no misleading numbers.
    assert bd.consistency == 0.0
    assert bd.volume_factor == 0.0
    assert bd.recency_factor == 0.0


def test_below_opportunities_floor_returns_zero():
    bd = score_with_breakdown(
        occurrences=5,
        opportunities=2,
        last_seen=NOW,
        now=NOW,
        config=_cfg(),
    )
    assert bd.score == 0.0
    assert bd.opportunities_passed is False


# ── three-factor product ───────────────────────────────────────────────────


def test_perfect_pattern_hits_ceiling():
    """High occurrences, perfect consistency, fresh — score = 1.0."""
    bd = score_with_breakdown(
        occurrences=10,
        opportunities=10,
        last_seen=NOW,
        now=NOW,
        config=_cfg(),
    )
    assert bd.consistency == 1.0
    assert bd.volume_factor == 1.0
    assert bd.recency_factor == 1.0
    assert bd.score == pytest.approx(1.0)


def test_volume_factor_caps_thin_evidence():
    """3-of-3 at perfect consistency must NOT score 1.0 — volume gate."""
    bd = score_with_breakdown(
        occurrences=3,
        opportunities=3,
        last_seen=NOW,
        now=NOW,
        config=_cfg(min_opportunities=3, min_confident_samples=10),
    )
    assert bd.consistency == 1.0
    assert bd.volume_factor == pytest.approx(0.3)
    assert bd.recency_factor == 1.0
    assert bd.score == pytest.approx(0.3)


def test_volume_factor_does_not_exceed_one():
    """Even 50 occurrences cap at 1.0 — no super-confidence runaway."""
    bd = score_with_breakdown(
        occurrences=50,
        opportunities=50,
        last_seen=NOW,
        now=NOW,
        config=_cfg(),
    )
    assert bd.volume_factor == 1.0


def test_consistency_drops_with_missed_opportunities():
    """5 of 10 weeks → consistency 0.5; volume still saturates."""
    bd = score_with_breakdown(
        occurrences=5,
        opportunities=10,
        last_seen=NOW,
        now=NOW,
        config=_cfg(min_occurrences_floor=3, min_confident_samples=5),
    )
    assert bd.consistency == pytest.approx(0.5)
    # min_confident_samples=5, occurrences=5 → 1.0
    assert bd.volume_factor == pytest.approx(1.0)
    assert bd.score == pytest.approx(0.5)


# ── recency ────────────────────────────────────────────────────────────────


def test_recency_factor_is_one_at_zero_days():
    bd = score_with_breakdown(
        occurrences=10,
        opportunities=10,
        last_seen=NOW,
        now=NOW,
        config=_cfg(),
    )
    assert bd.recency_factor == pytest.approx(1.0)


def test_recency_factor_at_half_life_is_about_one_over_e():
    cfg = _cfg(half_life_days=30.0)
    bd = score_with_breakdown(
        occurrences=10,
        opportunities=10,
        last_seen=NOW - timedelta(days=30),
        now=NOW,
        config=cfg,
    )
    assert bd.recency_factor == pytest.approx(math.exp(-1))


def test_recency_is_monotonic_decay():
    cfg = _cfg(half_life_days=10.0)
    values = []
    for days in [0, 5, 10, 20, 40]:
        bd = score_with_breakdown(
            occurrences=10,
            opportunities=10,
            last_seen=NOW - timedelta(days=days),
            now=NOW,
            config=cfg,
        )
        values.append(bd.recency_factor)
    assert all(values[i] > values[i + 1] for i in range(len(values) - 1))


def test_last_seen_in_the_future_treated_as_zero_days():
    """Clock-skew safety: a future last_seen does not invent extra recency."""
    bd = score_with_breakdown(
        occurrences=10,
        opportunities=10,
        last_seen=NOW + timedelta(days=5),
        now=NOW,
        config=_cfg(),
    )
    assert bd.days_since_last_seen == 0.0
    assert bd.recency_factor == 1.0


# ── penalty (forward-compat for 4.6) ───────────────────────────────────────


def test_penalty_half_halves_the_score():
    bd = score_with_breakdown(
        occurrences=10,
        opportunities=10,
        last_seen=NOW,
        now=NOW,
        config=_cfg(),
        penalty=0.5,
    )
    assert bd.score == pytest.approx(0.5)


def test_penalty_one_zeros_the_score():
    bd = score_with_breakdown(
        occurrences=10,
        opportunities=10,
        last_seen=NOW,
        now=NOW,
        config=_cfg(),
        penalty=1.0,
    )
    assert bd.score == pytest.approx(0.0)


def test_penalty_clamped_to_unit_interval():
    """Out-of-range penalty is clipped, not propagated as a negative score."""
    bd_neg = score_with_breakdown(
        occurrences=10,
        opportunities=10,
        last_seen=NOW,
        now=NOW,
        config=_cfg(),
        penalty=-0.5,
    )
    assert bd_neg.penalty == 0.0
    bd_huge = score_with_breakdown(
        occurrences=10,
        opportunities=10,
        last_seen=NOW,
        now=NOW,
        config=_cfg(),
        penalty=99.0,
    )
    assert bd_huge.penalty == 1.0
    assert bd_huge.score == 0.0


# ── score() shortcut + breakdown structure ─────────────────────────────────


def test_score_function_matches_breakdown():
    s = score(
        occurrences=10,
        opportunities=10,
        last_seen=NOW,
        now=NOW,
        config=_cfg(),
    )
    assert s == 1.0


def test_breakdown_explain_is_short_string():
    bd = score_with_breakdown(
        occurrences=8,
        opportunities=10,
        last_seen=NOW - timedelta(days=5),
        now=NOW,
        config=_cfg(),
    )
    text = bd.explain()
    assert "consistency" in text and "volume" in text and "recency" in text


def test_breakdown_dataclass_is_frozen():
    """Frozen so callers can't accidentally mutate a stored breakdown."""
    bd = score_with_breakdown(
        occurrences=10,
        opportunities=10,
        last_seen=NOW,
        now=NOW,
        config=_cfg(),
    )
    assert isinstance(bd, ConfidenceBreakdown)
    with pytest.raises((AttributeError, Exception)):
        bd.score = 0.5  # type: ignore[misc]
