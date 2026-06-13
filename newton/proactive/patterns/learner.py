"""Pattern learner — orchestrates detection runs and upserts ``user_patterns``.

The learner's job each call:

    1. compute the observation window: ``[now - observation_window_days, now]``
    2. for each detector (time, sequence; context is a stub):
        a. ask it for the list of observations in the window
        b. for each observation, find the matching user_patterns row by
           ``(user_id, pattern_type, pattern_data_json)``; insert or
           update in place
        c. recompute confidence from the row's fresh counts +
           ``last_seen`` and the live config
    3. report what changed

**occurrences is rewritten, not incremented.** The design doc said
"increment occurrences on match"; we set it to the current
in-window count instead. Two reasons:

    * idempotent: running ``learn --once`` twice gives the same
      ``user_patterns`` rows (incrementing would double-count).
    * decay-aware: a routine sir is dropping shows up as ``occurrences``
      shrinking, not just as recency_factor decaying.

This means the numerator naturally falls off as observations leave
the window — handling the same job recency does on the time axis,
but from the other side. ``observation_window_days`` is the source
of truth for both.

Context patterns are deferred — see ``patterns/context.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from newton.models.user_pattern import UserPattern
from newton.proactive.config import PatternsConfig, load_proactive_config
from newton.proactive.patterns import sequence, time_based
from newton.proactive.patterns.confidence import score


@dataclass
class LearnReport:
    """Summary of one learner run."""

    user_id: str
    window_start: datetime
    window_end: datetime
    inserted: int = 0
    updated: int = 0
    pattern_ids: list[int] = field(default_factory=list)
    expected_patterns_count: int = 0


def _canonical_json(obj: dict[str, Any]) -> str:
    """JSON with sorted keys so byte-equality means semantic equality."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


class PatternLearner:
    """Detect + score + upsert patterns for one user.

    Stateless apart from the config; safe to construct per-call.
    """

    def __init__(self, config: PatternsConfig | None = None) -> None:
        # Allow callers to inject; default to the freshly-loaded YAML.
        self._config = config or load_proactive_config().patterns

    @property
    def config(self) -> PatternsConfig:
        return self._config

    def run(
        self,
        db_session: Session,
        user_id: str,
        now: datetime | None = None,
    ) -> LearnReport:
        """Run every enabled detector for ``user_id``; upsert rows; rescore."""
        if now is None:
            now = datetime.now()

        window_start = now - timedelta(days=self._config.observation_window_days)
        report = LearnReport(
            user_id=user_id,
            window_start=window_start,
            window_end=now,
        )

        # ── time-based ────────────────────────────────────────────────
        time_obs = time_based.detect(
            db_session,
            user_id,
            window_start,
            self._config.pattern_timezone,
        )
        for obs in time_obs:
            self._upsert(
                db_session,
                user_id=user_id,
                pattern_type="time",
                signature=obs.signature(),
                occurrences=obs.occurrences,
                opportunities=obs.opportunities,
                last_seen=obs.last_seen,
                now=now,
                report=report,
            )

        # ── sequence ──────────────────────────────────────────────────
        seq_obs = sequence.detect(
            db_session,
            user_id,
            window_start,
            self._config.sequence.default_window_seconds,
        )
        for obs in seq_obs:
            self._upsert(
                db_session,
                user_id=user_id,
                pattern_type="sequence",
                signature=obs.signature(),
                occurrences=obs.occurrences,
                opportunities=obs.opportunities,
                last_seen=obs.last_seen,
                now=now,
                report=report,
            )

        # ── context: deferred ─────────────────────────────────────────
        # patterns/context.detect returns [] — see its module docstring
        # for why and what needs to land first.

        report.expected_patterns_count = report.inserted + report.updated
        return report

    def _upsert(
        self,
        db_session: Session,
        *,
        user_id: str,
        pattern_type: str,
        signature: dict[str, Any],
        occurrences: int,
        opportunities: int,
        last_seen: datetime,
        now: datetime,
        report: LearnReport,
    ) -> None:
        sig_json = _canonical_json(signature)
        existing = db_session.execute(
            select(UserPattern).where(
                UserPattern.user_id == user_id,
                UserPattern.pattern_type == pattern_type,
                UserPattern.pattern_data_json == sig_json,
            )
        ).scalar_one_or_none()

        conf = score(
            occurrences=occurrences,
            opportunities=opportunities,
            last_seen=last_seen,
            now=now,
            config=self._config,
        )

        if existing is None:
            row = UserPattern(
                user_id=user_id,
                pattern_type=pattern_type,
                pattern_data_json=sig_json,
                occurrences=occurrences,
                last_seen=last_seen,
                confidence=conf,
            )
            db_session.add(row)
            db_session.flush()  # populate pattern_id for the report
            report.inserted += 1
            report.pattern_ids.append(row.pattern_id)
        else:
            existing.occurrences = occurrences
            existing.last_seen = last_seen
            existing.confidence = conf
            report.updated += 1
            report.pattern_ids.append(existing.pattern_id)


__all__ = ["LearnReport", "PatternLearner"]
