"""Summarization triggers.

Decides *which* sessions are due for summarization. Two rules:

  1. Ended — ``ended_at`` is set and ``summarized_at`` is not.
  2. Idle — no ended_at, but the last message is older than the idle
     timeout (default 30 min); treated as abandoned and summarized.

The actual event wiring (a real "session ended" signal, a background
timer) belongs to the runtime in a later block. This module is the pure,
testable policy: given the DB and a clock, list what to summarize.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from newton.memory.summarizer import SessionSummarizer, summarize_session

DEFAULT_IDLE_MINUTES = 30


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def find_due_sessions(
    session: Any,
    *,
    now: datetime | None = None,
    idle_minutes: int = DEFAULT_IDLE_MINUTES,
) -> list[str]:
    """Return session_ids that should be summarized, oldest first."""
    from sqlalchemy import select

    from newton.models import ChatSession, Message

    now = now or datetime.now(timezone.utc)
    idle_cutoff = now - timedelta(minutes=idle_minutes)

    due: list[tuple[datetime, str]] = []
    rows = session.execute(select(ChatSession)).scalars().all()
    for cs in rows:
        if cs.summarized_at is not None:
            continue

        ended = _aware(cs.ended_at)
        if ended is not None:
            due.append((ended, cs.session_id))
            continue

        # Idle rule: look at the latest message time.
        last = session.execute(
            select(Message.created_at)
            .where(Message.session_id == cs.session_id)
            .order_by(Message.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        last = _aware(last)
        if last is not None and last < idle_cutoff:
            due.append((last, cs.session_id))

    due.sort(key=lambda t: t[0])
    return [sid for _ts, sid in due]


async def run_due_summarizations(
    session: Any,
    summarizer: SessionSummarizer,
    vault_root: Path,
    *,
    auto_dir: str = "_auto",
    now: datetime | None = None,
    idle_minutes: int = DEFAULT_IDLE_MINUTES,
) -> list[Path]:
    """Summarize every due session. Returns the note paths written."""
    paths: list[Path] = []
    for sid in find_due_sessions(session, now=now, idle_minutes=idle_minutes):
        path = await summarize_session(
            session, sid, summarizer, vault_root, auto_dir=auto_dir
        )
        if path is not None:
            paths.append(path)
    return paths


__all__ = [
    "DEFAULT_IDLE_MINUTES",
    "find_due_sessions",
    "run_due_summarizations",
]
