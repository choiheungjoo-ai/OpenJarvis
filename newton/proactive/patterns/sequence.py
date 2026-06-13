"""Sequence pattern detection — "X often follows Y within a window".

For every ordered pair ``(A, B)`` of tool names sir has actually run
(``decision='approved'``) in the observation window, we count:

    numerator   = # of A-events that have at least one B-event within
                  ``window_seconds`` *after* them
    denominator = # of A-events (after back-to-back A dedupe)

Back-to-back A dedupe
---------------------
If sir ran ``vault_search`` three times in 90 seconds, that's *one*
opportunity for the ``vault_search → vault_write`` rule, not three.
Without dedupe a Saturday hammering of one tool would inflate the
denominator and crater consistency.

Rule: when iterating A-events in time order, an A-event is "absorbed"
into the previous A-event if its timestamp is within ``window_seconds``
of the previous *kept* A-event. The first A in a burst is the one
that anchors numerator-lookup.

Approved-only
-------------
We read from ``approved_tool_runs_in_window`` — ``denied`` / ``timeout``
rows are not opportunities (the tool didn't actually execute, so no
follow-on behaviour could have happened).

Pair enumeration
----------------
A naive Cartesian over all tool names blows up. We only emit a pair
``(A, B)`` if at least one B-event ever followed an A-event within
the window — observed pairs only. Patterns that never happened don't
need rows in ``user_patterns``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from newton.proactive.patterns.series import approved_tool_runs_in_window


@dataclass(frozen=True, slots=True)
class SequencePatternObservation:
    """One detected A→B-within-window pair."""

    after_tool: str
    then_tool: str
    within_seconds: int
    occurrences: int
    opportunities: int
    last_seen: datetime  # UTC; the timestamp of the most recent A that satisfied

    def signature(self) -> dict[str, Any]:
        """Stable JSON-serialisable id for ``user_patterns.pattern_data_json``."""
        return {
            "kind": "sequence",
            "after_tool": self.after_tool,
            "then_tool": self.then_tool,
            "within_seconds": self.within_seconds,
        }


def _dedupe_back_to_back(events: list[datetime], window_seconds: int) -> list[datetime]:
    """Collapse A-events that fall within ``window_seconds`` of the previous kept A."""
    kept: list[datetime] = []
    window = timedelta(seconds=window_seconds)
    for t in events:
        if not kept or t - kept[-1] > window:
            kept.append(t)
    return kept


def detect(
    session: Session,
    user_id: str,
    window_start: datetime,
    window_seconds: int,
) -> list[SequencePatternObservation]:
    """Find every observed A→B pair and compute its counts."""
    runs = approved_tool_runs_in_window(session, user_id, window_start)

    # tool -> [decided_at, ...] in time order
    by_tool: dict[str, list[datetime]] = defaultdict(list)
    for r in runs:
        by_tool[r.tool_name].append(r.decided_at)

    # All approved events in time order, for fast B-lookup per A
    by_time: list[tuple[datetime, str]] = sorted(
        ((r.decided_at, r.tool_name) for r in runs), key=lambda x: x[0]
    )

    observations: list[SequencePatternObservation] = []
    window = timedelta(seconds=window_seconds)

    for after_tool, raw_times in by_tool.items():
        # Denominator: distinct A-events after dedupe.
        a_anchors = _dedupe_back_to_back(raw_times, window_seconds)
        if not a_anchors:
            continue

        # For each potential B-tool, count anchors that have at least
        # one B-event within (anchor, anchor + window].
        # b_count_per_tool[b] = numerator-anchors-for-this-B
        b_count_per_tool: dict[str, int] = defaultdict(int)
        b_last_seen_per_tool: dict[str, datetime] = {}

        for anchor in a_anchors:
            # Walk forward from anchor in by_time to find B-events in
            # window. by_time is sorted; this is O(events_in_window).
            #
            # bisect would be cleaner; for the volumes a personal AI
            # OS sees (hundreds of runs per month), the linear walk
            # is fine and easier to read.
            seen_in_this_window: set[str] = set()
            limit = anchor + window
            for t, tool in by_time:
                if t <= anchor:
                    continue
                if t > limit:
                    break
                if tool == after_tool:
                    # Don't credit B = A (it's already handled by dedupe);
                    # a same-tool burst isn't an A→B pattern.
                    continue
                seen_in_this_window.add(tool)
            for b in seen_in_this_window:
                b_count_per_tool[b] += 1
                # last_seen: the most recent anchor where this B fired.
                prev = b_last_seen_per_tool.get(b)
                if prev is None or anchor > prev:
                    b_last_seen_per_tool[b] = anchor

        denom = len(a_anchors)
        for then_tool, num in b_count_per_tool.items():
            observations.append(
                SequencePatternObservation(
                    after_tool=after_tool,
                    then_tool=then_tool,
                    within_seconds=window_seconds,
                    occurrences=num,
                    opportunities=denom,
                    last_seen=b_last_seen_per_tool[then_tool],
                )
            )

    observations.sort(key=lambda o: (o.after_tool, o.then_tool))
    return observations


__all__ = ["SequencePatternObservation", "detect"]
