"""Anticipation engine — block 4 step 4.4.

The engine turns *learned* patterns (step 4.3) into *predicted next
actions* for the moment we're predicting for. It does **not** re-derive
confidence: the score the pattern learner already wrote is what we
trust. Live re-derivation per-tick would call
``_recompute_opportunities`` and re-scan the observation window — fine
for ``patterns show``, way too expensive for an engine the scheduler
will hit every minute or so.

Final score
-----------
::

    final = confidence × relevance(pattern, now)

* ``confidence`` is read directly from ``user_patterns.confidence`` —
  the value the last learn run wrote.
* ``relevance`` is a 0..1 number from a swappable
  :class:`RelevanceStrategy`. The default
  (:class:`TimeProximityRelevance`) decays with Gaussian distance from
  the predicted ETA for time patterns, and is binary for sequence
  patterns (1.0 if the A-event ran inside the relevance window, else
  0.0). New strategies (calendar-weighted, screen-context-weighted, …)
  plug in without changing the engine.

Mode gating
-----------
Each prediction's ``final`` is compared against
``config.anticipation.thresholds[mode]``. Modes (``off``,
``minimal``, ``smart``, ``aggressive``) live in config; the engine
holds no thresholds of its own. ``off`` uses a value > 1.0 so no
score ever crosses — the threshold check stays a plain ``>=`` with
no special-case for the off mode.

Rationale
---------
Every :class:`Prediction` carries a :class:`Rationale` that breaks
final into its inputs (confidence, relevance, factors specific to the
strategy, mode threshold passed/failed). The CLI prints it; tests
assert on it. No black box.
"""

from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from newton.models.user_pattern import UserPattern
from newton.proactive.config import (
    AnticipationConfig,
    ReactionLearningConfig,
    load_proactive_config,
)
from newton.proactive.context import Context
from newton.proactive.learning import compute_pattern_penalty
from newton.proactive.patterns.series import to_local

# ─────────────────────────────────────────────────────────────────────────────
# Prediction + rationale
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Rationale:
    """How the engine arrived at ``final``."""

    confidence: float
    relevance: float
    final: float
    mode: str
    threshold: float
    threshold_passed: bool
    factors: dict[str, Any] = field(default_factory=dict)
    penalty: float = 0.0  # cumulative reaction penalty (step 4.6)

    def explain(self) -> str:
        """One-line summary suitable for the CLI."""
        return (
            f"confidence {self.confidence:.3f} × "
            f"(1 - penalty {self.penalty:.3f}) × "
            f"relevance {self.relevance:.3f} = {self.final:.3f} "
            f"vs {self.mode} threshold {self.threshold:.2f} "
            f"({'pass' if self.threshold_passed else 'fail'})"
        )


@dataclass(frozen=True, slots=True)
class Prediction:
    """One ranked predicted action."""

    pattern_id: int
    pattern_type: str
    action: str
    final: float
    eta: datetime | None
    notification_text: str
    rationale: Rationale


# ─────────────────────────────────────────────────────────────────────────────
# Relevance strategy (swappable)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RelevanceResult:
    """Strategy output: a relevance number, an ETA, and explainable factors."""

    relevance: float
    eta: datetime | None
    factors: dict[str, Any]


class RelevanceStrategy(ABC):
    """How relevant is a pattern *right now*? Swap to change the engine's bias."""

    @abstractmethod
    def evaluate(
        self,
        *,
        pattern: UserPattern,
        signature: dict[str, Any],
        context: Context,
        config: AnticipationConfig,
        tz_name: str,
    ) -> RelevanceResult: ...


class TimeProximityRelevance(RelevanceStrategy):
    """Default strategy.

    Time pattern:
        Find the closest occurrence of ``(weekday, hour)`` to ``now`` in
        ``tz_name`` (past or future, whichever is nearer); relevance is
        a Gaussian centred at the ETA with σ = ``relevance_sigma_minutes``.
        ETA is the nearest *future* occurrence so the scheduler can use
        it as "fires at".

    Sequence pattern:
        relevance = 1.0 iff the ``after_tool`` ran inside the last
        ``sequence_relevance_seconds``; otherwise 0.0. ETA is
        ``last_run_of(after_tool) + within_seconds`` — the moment the
        window for B closes.

    Unknown ``signature.kind``:
        relevance = 0.0. Better silent than a wrong guess.
    """

    def evaluate(
        self,
        *,
        pattern: UserPattern,
        signature: dict[str, Any],
        context: Context,
        config: AnticipationConfig,
        tz_name: str,
    ) -> RelevanceResult:
        kind = signature.get("kind")

        if kind == "weekly":
            return self._evaluate_weekly(signature, context, config, tz_name)
        if kind == "sequence":
            return self._evaluate_sequence(signature, context, config)

        return RelevanceResult(
            relevance=0.0,
            eta=None,
            factors={"unknown_kind": kind},
        )

    # ── weekly ───────────────────────────────────────────────────────

    def _evaluate_weekly(
        self,
        signature: dict[str, Any],
        context: Context,
        config: AnticipationConfig,
        tz_name: str,
    ) -> RelevanceResult:
        weekday = int(signature["weekday"])
        hour = int(signature["hour"])

        local_now = to_local(context.now, tz_name)
        # Find the (weekday, hour) occurrence on or after local_now,
        # then also the previous occurrence; keep the closer one for
        # relevance, but use the FUTURE occurrence as ETA so the
        # scheduler can use it as a fire-at.
        days_ahead = (weekday - local_now.weekday()) % 7
        next_local = (local_now + timedelta(days=days_ahead)).replace(
            hour=hour, minute=0, second=0, microsecond=0
        )
        if next_local < local_now:
            next_local = next_local + timedelta(days=7)
        prev_local = next_local - timedelta(days=7)

        delta_to_next = abs((next_local - local_now).total_seconds())
        delta_to_prev = abs((local_now - prev_local).total_seconds())
        closer_delta = min(delta_to_next, delta_to_prev)

        sigma_s = config.relevance_sigma_minutes * 60.0
        # Gaussian: exp(-(d/σ)² / 2) ⇒ at d=σ, value≈0.61; at d=2σ ≈0.13
        relevance = math.exp(-((closer_delta / sigma_s) ** 2) / 2.0)

        # ETA back to UTC-naive so it round-trips with stored timestamps.
        from zoneinfo import ZoneInfo

        eta_utc = (
            next_local.replace(tzinfo=ZoneInfo(tz_name))
            .astimezone(ZoneInfo("UTC"))
            .replace(tzinfo=None)
        )

        return RelevanceResult(
            relevance=relevance,
            eta=eta_utc,
            factors={
                "delta_minutes_to_closest": round(closer_delta / 60.0, 2),
                "sigma_minutes": config.relevance_sigma_minutes,
                "next_eta_local": next_local.isoformat(),
            },
        )

    # ── sequence ──────────────────────────────────────────────────────

    def _evaluate_sequence(
        self,
        signature: dict[str, Any],
        context: Context,
        config: AnticipationConfig,
    ) -> RelevanceResult:
        after_tool = signature["after_tool"]
        within_seconds = int(signature.get("within_seconds", 600))

        last_a = context.last_run_of(after_tool)
        if last_a is None:
            return RelevanceResult(
                relevance=0.0,
                eta=None,
                factors={
                    "after_tool": after_tool,
                    "last_run_of_a": None,
                    "reason": "after_tool not run recently",
                },
            )

        delta = (context.now - last_a).total_seconds()
        # In window ⇒ fully relevant; outside ⇒ irrelevant. The relevance
        # window is the smaller of the pattern's within_seconds and the
        # config-level sequence_relevance_seconds so config can globally
        # tighten without per-pattern edits.
        relevance_window = min(within_seconds, config.sequence_relevance_seconds)
        in_window = 0 <= delta <= relevance_window
        relevance = 1.0 if in_window else 0.0
        eta = last_a + timedelta(seconds=within_seconds) if in_window else None
        return RelevanceResult(
            relevance=relevance,
            eta=eta,
            factors={
                "after_tool": after_tool,
                "last_run_of_a": last_a.isoformat(),
                "seconds_since_a": round(delta, 1),
                "relevance_window_seconds": relevance_window,
            },
        )


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────


class AnticipationEngine:
    """Read learned patterns, score them against ``now``, return ranked predictions."""

    def __init__(
        self,
        config: AnticipationConfig | None = None,
        relevance: RelevanceStrategy | None = None,
        pattern_timezone: str = "Asia/Seoul",
        reactions: ReactionLearningConfig | None = None,
    ) -> None:
        cfg = load_proactive_config()
        self._config = config or cfg.anticipation
        self._relevance = relevance or TimeProximityRelevance()
        self._tz_name = pattern_timezone
        self._reactions = reactions or cfg.reactions

    @property
    def config(self) -> AnticipationConfig:
        return self._config

    def predict(
        self,
        db_session: Session,
        context: Context,
        mode: str | None = None,
    ) -> list[Prediction]:
        """Return at most ``config.max_results`` predictions for ``context.user_id``.

        Returns predictions sorted by ``final`` descending. ``mode``
        overrides ``config.default_mode``; step 4.8 will pass
        ``users.proactive_mode`` here.
        """
        chosen_mode = mode or self._config.default_mode
        threshold = self._threshold_for(chosen_mode)

        rows = list(
            db_session.execute(
                select(UserPattern).where(UserPattern.user_id == context.user_id)
            )
            .scalars()
            .all()
        )

        predictions: list[Prediction] = []
        for row in rows:
            sig = self._signature(row)
            if sig is None:
                continue
            confidence = float(row.confidence or 0.0)
            if confidence <= 0.0:
                # Patterns the learner zeroed out (sub-floor, decayed,
                # etc.) shouldn't reach the mode threshold anyway —
                # short-circuit so they don't even appear in
                # explain logs.
                continue

            rr = self._relevance.evaluate(
                pattern=row,
                signature=sig,
                context=context,
                config=self._config,
                tz_name=self._tz_name,
            )
            # Reaction penalty folds in here (4.6). Computed live so
            # toggling sir's recent reactions is reflected immediately;
            # the cost is one indexed query per pattern per predict()
            # call — fine at the volumes the scheduler runs at.
            penalty = compute_pattern_penalty(
                db_session,
                context.user_id,
                row.pattern_id,
                self._reactions,
                now=context.now,
            )
            effective_confidence = confidence * (1.0 - penalty)
            final = effective_confidence * rr.relevance
            rationale = Rationale(
                confidence=confidence,
                relevance=rr.relevance,
                final=final,
                mode=chosen_mode,
                threshold=threshold,
                threshold_passed=(final >= threshold),
                factors=rr.factors,
                penalty=penalty,
            )
            if not rationale.threshold_passed:
                continue

            predictions.append(
                Prediction(
                    pattern_id=row.pattern_id,
                    pattern_type=row.pattern_type,
                    action=self._action(row.pattern_type, sig),
                    final=final,
                    eta=rr.eta,
                    notification_text=self._notification_text(row.pattern_type, sig),
                    rationale=rationale,
                )
            )

        predictions.sort(key=lambda p: p.final, reverse=True)
        return predictions[: self._config.max_results]

    # ── helpers ──────────────────────────────────────────────────────

    def _threshold_for(self, mode: str) -> float:
        thresholds = self._config.thresholds
        if mode == "off":
            return thresholds.off
        if mode == "minimal":
            return thresholds.minimal
        if mode == "smart":
            return thresholds.smart
        if mode == "aggressive":
            return thresholds.aggressive
        # Unknown mode → conservative fallback (smart). Better than
        # silently using a permissive value.
        return thresholds.smart

    @staticmethod
    def _signature(row: UserPattern) -> dict[str, Any] | None:
        if not row.pattern_data_json:
            return None
        try:
            return json.loads(row.pattern_data_json)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _action(pattern_type: str, signature: dict[str, Any]) -> str:
        """A short stable label for the action this pattern predicts."""
        if pattern_type == "time" and signature.get("kind") == "weekly":
            return f"weekly_w{signature['weekday']}_h{signature['hour']:02d}"
        if pattern_type == "sequence" and signature.get("kind") == "sequence":
            return f"after_{signature['after_tool']}_then_{signature['then_tool']}"
        return f"{pattern_type}_unknown"

    @staticmethod
    def _notification_text(pattern_type: str, signature: dict[str, Any]) -> str:
        """The first-pass user-facing prose. Block 5's voice layer will polish."""
        if pattern_type == "time" and signature.get("kind") == "weekly":
            hour = signature["hour"]
            return f"Sir, you usually start a session around {hour:02d}:00."
        if pattern_type == "sequence" and signature.get("kind") == "sequence":
            return (
                f"Sir, you just ran {signature['after_tool']} — "
                f"want to run {signature['then_tool']} next?"
            )
        return "Sir, a pattern matched the current moment."


__all__ = [
    "AnticipationEngine",
    "Prediction",
    "Rationale",
    "RelevanceResult",
    "RelevanceStrategy",
    "TimeProximityRelevance",
]
