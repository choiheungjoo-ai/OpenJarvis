"""Time-based pattern detection — weekly / daily routines.

A pattern is a ``(weekday, hour)`` bucket in *local* time (the
configured ``pattern_timezone``) where sir consistently starts a
session.

Numerator / denominator
-----------------------
For each ``(weekday, hour)`` bucket:

    numerator   = # of sessions started in this bucket within the window
    denominator = # of distinct local-dates *of this weekday* on which
                  sir started any session at all, within the window

Denominator = "of the Tuesdays in the window, how many had sir
engaged at all" — the cleanest proxy for "opportunity to repeat the
Tuesday-9am routine" available from the existing tables.

Skews we accept:
    * a Tuesday with 30 sessions counts the same as one with 1 session
    * we do *not* use ``system_metrics`` as a presence proxy — the
      daemon samples 24/7 even when sir's away from the machine, so
      a "metrics ⇒ presence" rule would inflate the denominator.

UTC vs local
------------
SQLite stores naive UTC. Bucketing by weekday/hour must shift through
``pattern_timezone`` first — same trap step 4.2 hit with sent_at.
:func:`newton.proactive.patterns.series.to_local` does the conversion.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from newton.proactive.patterns.series import sessions_in_window, to_local


@dataclass(frozen=True, slots=True)
class TimePatternObservation:
    """One detected (weekday, hour) bucket with counts and a last-seen."""

    weekday: int  # 0 = Monday, 6 = Sunday (datetime.weekday())
    hour: int  # 0..23 in local time
    occurrences: int
    opportunities: int
    last_seen: datetime  # UTC

    def signature(self) -> dict[str, Any]:
        """Stable JSON-serialisable id used in ``user_patterns.pattern_data_json``."""
        return {
            "kind": "weekly",
            "weekday": self.weekday,
            "hour": self.hour,
        }


def detect(
    session: Session,
    user_id: str,
    window_start: datetime,
    tz_name: str,
) -> list[TimePatternObservation]:
    """Bucket sessions by local (weekday, hour) and emit one observation per bucket.

    Returns one entry for every bucket with at least one session — the
    learner / scorer applies the floor + opportunity gates. Buckets
    with no sessions are left out (no row to write).
    """
    rows = sessions_in_window(session, user_id, window_start)

    # numerator[(weekday, hour)] = list of UTC started_at values
    numerator: dict[tuple[int, int], list[datetime]] = defaultdict(list)

    # denominator_dates_per_weekday[weekday] = set of local date strings
    # on which sir had any session at all. The denominator is the size
    # of this set per weekday.
    denominator_dates_per_weekday: dict[int, set[str]] = defaultdict(set)

    for row in rows:
        local = to_local(row.started_at, tz_name)
        wd = local.weekday()
        hr = local.hour
        numerator[(wd, hr)].append(row.started_at)
        denominator_dates_per_weekday[wd].add(local.date().isoformat())

    observations: list[TimePatternObservation] = []
    for (wd, hr), starts in numerator.items():
        opp = len(denominator_dates_per_weekday[wd])
        observations.append(
            TimePatternObservation(
                weekday=wd,
                hour=hr,
                occurrences=len(starts),
                opportunities=opp,
                last_seen=max(starts),
            )
        )

    # Stable order makes the learner's upsert and the tests deterministic.
    observations.sort(key=lambda o: (o.weekday, o.hour))
    return observations


__all__ = ["TimePatternObservation", "detect"]
