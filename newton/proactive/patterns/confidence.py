"""Three-factor confidence scoring for ``user_patterns``.

The doc's original ``confidence = min(1.0, occurrences / 10)`` is too
weak: it counts frequency only, hardcodes ``10``, and ignores both
consistency (occurrences vs *opportunities*) and recency. The model
below replaces it with three observable factors plus a forward-compat
penalty term that step 4.6's rejection learning will populate.

The math::

    raw = consistency × volume_factor × recency_factor × (1 - penalty)
    confidence = clamp(raw, 0.0, 1.0)

Pre-filters (gates that short-circuit to ``0.0`` before any factor is
computed):

    * ``occurrences < min_occurrences_floor`` — numerator too thin.
    * ``opportunities < min_opportunities`` — denominator too noisy.

Why "computed on demand, not persisted":
    The learner stores ``confidence`` in ``user_patterns`` so reads
    (anticipation engine in 4.4, CLI ``patterns list``) are cheap. But
    the *breakdown* is recomputed from the row + current config + now.
    If sir tunes ``half_life_days`` between learn runs, the displayed
    breakdown reflects current config; the stored confidence will
    update on the next learn run. ``patterns show`` displays both so
    the divergence is visible, not silent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from newton.proactive.config import PatternsConfig


@dataclass(frozen=True, slots=True)
class ConfidenceBreakdown:
    """A scoring decision with every input visible.

    Every numeric field that contributes to ``score`` is here, so a
    debug surface can print *why* a pattern landed at 0.62.
    """

    # Inputs
    occurrences: int
    opportunities: int
    days_since_last_seen: float
    penalty: float

    # Pre-filter outcome
    floor_passed: bool
    opportunities_passed: bool

    # Factors (0.0 if a pre-filter blocked them)
    consistency: float
    volume_factor: float
    recency_factor: float

    # Result
    raw: float
    score: float

    def explain(self) -> str:
        """One-line human summary suitable for the CLI."""
        if not self.floor_passed:
            return f"occurrences {self.occurrences} < floor → score 0.0"
        if not self.opportunities_passed:
            return f"opportunities {self.opportunities} < min → score 0.0"
        return (
            f"consistency {self.consistency:.3f} × "
            f"volume {self.volume_factor:.3f} × "
            f"recency {self.recency_factor:.3f} × "
            f"(1-penalty {self.penalty:.3f}) = {self.score:.3f}"
        )


def _days_between(now: datetime, then: datetime | None) -> float:
    """Days between ``then`` and ``now``; treats missing ``then`` as 0."""
    if then is None:
        return 0.0
    delta: timedelta = now - then
    return max(0.0, delta.total_seconds() / 86400.0)


def score_with_breakdown(
    *,
    occurrences: int,
    opportunities: int,
    last_seen: datetime | None,
    now: datetime,
    config: PatternsConfig,
    penalty: float = 0.0,
) -> ConfidenceBreakdown:
    """Compute confidence and return every factor that produced it."""
    days_since = _days_between(now, last_seen)
    penalty = max(0.0, min(1.0, penalty))

    floor_passed = occurrences >= config.min_occurrences_floor
    opp_passed = opportunities >= config.min_opportunities

    if not floor_passed or not opp_passed:
        return ConfidenceBreakdown(
            occurrences=occurrences,
            opportunities=opportunities,
            days_since_last_seen=days_since,
            penalty=penalty,
            floor_passed=floor_passed,
            opportunities_passed=opp_passed,
            consistency=0.0,
            volume_factor=0.0,
            recency_factor=0.0,
            raw=0.0,
            score=0.0,
        )

    # consistency = how often the pattern fires when it *could*
    consistency = min(1.0, occurrences / opportunities)

    # volume_factor caps thin evidence: 3-of-3 at perfect consistency
    # shouldn't read as 1.0.
    volume_factor = min(1.0, occurrences / config.min_confident_samples)

    # recency_factor decays a stale routine. half_life_days is the
    # configured "should still be ≈0.37 at this age" mark.
    recency_factor = math.exp(-days_since / config.half_life_days)

    raw = consistency * volume_factor * recency_factor * (1.0 - penalty)
    final = max(0.0, min(1.0, raw))

    return ConfidenceBreakdown(
        occurrences=occurrences,
        opportunities=opportunities,
        days_since_last_seen=days_since,
        penalty=penalty,
        floor_passed=True,
        opportunities_passed=True,
        consistency=consistency,
        volume_factor=volume_factor,
        recency_factor=recency_factor,
        raw=raw,
        score=final,
    )


def score(
    *,
    occurrences: int,
    opportunities: int,
    last_seen: datetime | None,
    now: datetime,
    config: PatternsConfig,
    penalty: float = 0.0,
) -> float:
    """Bare confidence in [0, 1]. Use :func:`score_with_breakdown` for debugging."""
    return score_with_breakdown(
        occurrences=occurrences,
        opportunities=opportunities,
        last_seen=last_seen,
        now=now,
        config=config,
        penalty=penalty,
    ).score


__all__ = ["ConfidenceBreakdown", "score", "score_with_breakdown"]
