"""Current-moment context for the anticipation engine.

A :class:`Context` is the read-only snapshot the engine consults when
deciding *now* what sir might want. For step 4.4 it carries:

    * ``now``           — the moment we're predicting for (injectable for tests)
    * ``user_id``       — whose patterns we consider
    * ``recent_runs``   — recently approved tool calls, for sequence
                          relevance ("A just ran, is B usually next?")

Calendar handles, active sessions, ambient signals, and screen state
join later (blocks 5–9). The shape is small on purpose: every field is
something a detector actually consumes, not something we *might* want.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from newton.models.tool_approval import ToolApproval


@dataclass(frozen=True, slots=True)
class Context:
    """Read-only snapshot the anticipation engine consults."""

    user_id: str
    now: datetime
    recent_runs: list[ToolApproval] = field(default_factory=list)

    def last_run_of(self, tool_name: str) -> datetime | None:
        """Most-recent ``decided_at`` of ``tool_name`` in ``recent_runs``."""
        latest: datetime | None = None
        for r in self.recent_runs:
            if r.tool_name != tool_name:
                continue
            if latest is None or r.decided_at > latest:
                latest = r.decided_at
        return latest


def assemble(
    session: Session,
    user_id: str,
    now: datetime | None = None,
    lookback_seconds: int = 600,
) -> Context:
    """Build a :class:`Context` for ``user_id`` at ``now``.

    ``lookback_seconds`` is wide enough by default to catch every
    sequence pattern's A-event under the shipped config; the scheduler
    (step 4.5) may widen it for longer-window rules without changing
    this signature — just pass the larger value.
    """
    if now is None:
        now = datetime.now()
    cutoff = now - timedelta(seconds=lookback_seconds)
    runs = list(
        session.execute(
            select(ToolApproval)
            .where(
                ToolApproval.user_id == user_id,
                ToolApproval.decision == "approved",
                ToolApproval.decided_at >= cutoff,
            )
            .order_by(ToolApproval.decided_at)
        )
        .scalars()
        .all()
    )
    return Context(user_id=user_id, now=now, recent_runs=runs)


__all__ = ["Context", "assemble"]
