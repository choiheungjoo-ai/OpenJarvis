"""Quiet-hours predicate — block 4 step 4.5.

A configurable daily window during which the scheduler stays silent
unless a notification is flagged ``urgent``. The window may wrap
midnight (the typical case: 23:00–07:00).

Local-time, not UTC. SQLite stores naive UTC; we shift through
``config.patterns.pattern_timezone`` before comparing — same UTC-vs-
local trap step 4.2 hit with ``sent_at`` and step 4.3 hit with
weekday bucketing.

Step 4.8 will add ``users.timezone`` and let the scheduler read per-user
windows; until then the system-wide ``pattern_timezone`` is the source
of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class QuietHoursWindow:
    """A daily window ``[start, end)`` in local time, possibly wrapping midnight."""

    start: time
    end: time
    tz_name: str

    def is_quiet(self, now: datetime) -> bool:
        """True if ``now`` (naive UTC) lies inside the window in ``tz_name``."""
        if self.start == self.end:
            return False  # zero-length window ⇒ never quiet
        local = self._to_local(now).time()
        if self.start <= self.end:
            # Same-day window, e.g. 12:00–14:00
            return self.start <= local < self.end
        # Wrap-around, e.g. 23:00–07:00 ⇒ [23:00, 24:00) ∪ [00:00, 07:00)
        return local >= self.start or local < self.end

    def _to_local(self, dt: datetime) -> datetime:
        if dt.tzinfo is not None:
            return dt.astimezone(ZoneInfo(self.tz_name)).replace(tzinfo=None)
        return (
            dt.replace(tzinfo=ZoneInfo("UTC"))
            .astimezone(ZoneInfo(self.tz_name))
            .replace(tzinfo=None)
        )


def parse_hhmm(s: str) -> time:
    """Parse 'HH:MM' into ``datetime.time``. Raises on bad input."""
    parts = s.split(":")
    if len(parts) != 2:
        raise ValueError(f"expected HH:MM, got {s!r}")
    hh = int(parts[0])
    mm = int(parts[1])
    return time(hour=hh, minute=mm)


__all__ = ["QuietHoursWindow", "parse_hhmm"]
