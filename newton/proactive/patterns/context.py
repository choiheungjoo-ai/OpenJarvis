"""Context pattern detection — DEFERRED.

The design doc's example was:

    "when battery_percent < 25 AND time > 21:00,
     sir tends to shut down."

We're not shipping this in step 4.3 because two prerequisites are
missing from the current schema, and faking either one would produce
patterns that *look* reasonable but rest on bad data.

Problem 1 — what is an "action"?
    The doc's example action is *shutdown*. There is no shutdown event
    in the schema. The closest signal is ``sessions.ended_at``, but
    sessions end for many reasons (user closed a tab, timed out,
    summarised) — equating that with "sir shut down" would silently
    misattribute. A clean implementation needs an explicit event of
    the kind 4.5's runtime or 4.6's reaction tracker will provide.

Problem 2 — opportunity counting requires *episode* detection.
    Preconditions like "battery < 25" hold continuously, but
    ``system_metrics`` stores discrete samples (one row per ~60 s).
    Naively counting samples that meet the preconditions inflates the
    denominator: a 90-minute dip below 25% at 60 s sampling looks
    like 90 opportunities, not one. The right unit is an *episode* —
    a maximal contiguous stretch of samples that meet the
    preconditions — which is non-trivial to detect correctly when
    samples can be missing (daemon paused, machine asleep) or when
    multiple preconditions need to align.

What we ship instead in 4.3:
    :func:`detect` returns ``[]``. ``pattern_type='context'`` is
    already in migration 001's CHECK constraint, so when a later
    block lands the action event and episode detection, dropping a
    real detector in here is purely additive — no migration, no
    learner change.

What needs to land first, in rough order:
    1. A *session lifecycle* event stream (login / lock / shutdown
       distinct from sessions.ended_at). Likely block 5 runtime
       or block 7 OS-command surface.
    2. An ``EpisodeFinder`` helper in :mod:`series` that collapses
       contiguous matching samples into ``[start, end)`` episodes,
       with a tunable max-gap so brief missing samples don't split
       one episode into many.
    3. A precondition DSL — the doc's
       ``[{"metric":"battery_percent","op":"<","value":25},
         {"time_after":"21:00"}]`` is already a reasonable shape; it
       just needs a stable evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class ContextPatternObservation:
    """Placeholder dataclass so the API mirrors time_based / sequence.

    No code constructs an instance until the gaps in this module's
    docstring are closed.
    """

    occurrences: int
    opportunities: int
    last_seen: datetime
    preconditions: list[dict[str, Any]]
    action: str

    def signature(self) -> dict[str, Any]:
        return {
            "kind": "context",
            "preconditions": self.preconditions,
            "action": self.action,
        }


def detect(
    session: Session,  # noqa: ARG001
    user_id: str,  # noqa: ARG001
    window_start: datetime,  # noqa: ARG001
) -> list[ContextPatternObservation]:
    """Context detection is deferred; see module docstring."""
    return []


__all__ = ["ContextPatternObservation", "detect"]
