"""Time-series read helpers for pattern detection.

This module exists to keep the alert checker and the pattern learner on
separate read paths against ``system_metrics`` / ``sessions`` /
``tool_approvals``. The alert checker (step 4.2) reads one *latest*
sample; the pattern learner reads a *window* of rows. The two shapes
must not merge — otherwise the alert checker grows a window parameter
it doesn't need, and pattern false-positives could leak into the
threshold path.

All helpers below take an explicit ``window_start`` (UTC datetime) so
the caller decides the observation window — usually ``now -
observation_window_days``. They return raw rows; bucketing into
weekdays / hours and dedupe of back-to-back events live in the
detector modules that consume these helpers.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from newton.models.chat_session import ChatSession
from newton.models.tool_approval import ToolApproval


def sessions_in_window(
    session: Session,
    user_id: str,
    window_start: datetime,
) -> list[ChatSession]:
    """Return ``ChatSession`` rows for ``user_id`` started on/after ``window_start``."""
    return list(
        session.execute(
            select(ChatSession)
            .where(
                ChatSession.user_id == user_id,
                ChatSession.started_at >= window_start,
            )
            .order_by(ChatSession.started_at)
        )
        .scalars()
        .all()
    )


def approved_tool_runs_in_window(
    session: Session,
    user_id: str,
    window_start: datetime,
) -> list[ToolApproval]:
    """Return ``decision='approved'`` tool runs for ``user_id`` in the window.

    Sequence patterns are about tools that actually ran — denied or
    timed-out approvals shouldn't appear in either the numerator or
    the denominator.
    """
    return list(
        session.execute(
            select(ToolApproval)
            .where(
                ToolApproval.user_id == user_id,
                ToolApproval.decision == "approved",
                ToolApproval.decided_at >= window_start,
            )
            .order_by(ToolApproval.decided_at)
        )
        .scalars()
        .all()
    )


def to_local(dt: datetime, tz_name: str) -> datetime:
    """Shift a naive UTC ``datetime`` into the given timezone, returning naive local.

    SQLite stores naive UTC timestamps. For weekday / hour bucketing
    we need the local-time interpretation. We attach UTC, convert to
    ``tz_name``, then strip the tzinfo so the caller works with naive
    local datetimes throughout.
    """
    if dt.tzinfo is not None:
        # Caller already attached a tz — trust it.
        return dt.astimezone(ZoneInfo(tz_name)).replace(tzinfo=None)
    return (
        dt.replace(tzinfo=ZoneInfo("UTC"))
        .astimezone(ZoneInfo(tz_name))
        .replace(tzinfo=None)
    )


__all__ = [
    "approved_tool_runs_in_window",
    "sessions_in_window",
    "to_local",
]
