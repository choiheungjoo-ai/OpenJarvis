"""Tests for time-based pattern detection."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from newton.db import get_session, init_db
from newton.models.chat_session import ChatSession
from newton.models.user import User
from newton.proactive.patterns import time_based


def _utc(dt_local: datetime, tz: str = "Asia/Seoul") -> datetime:
    return (
        dt_local.replace(tzinfo=ZoneInfo(tz))
        .astimezone(ZoneInfo("UTC"))
        .replace(tzinfo=None)
    )


def _seed_user(user_id: str = "sir") -> None:
    with get_session() as s:
        if s.get(User, user_id) is None:
            s.add(User(user_id=user_id, display_name="Sir"))


def _seed_persona(persona_id: str = "jarvis") -> None:
    from newton.models.persona import Persona

    with get_session() as s:
        if s.get(Persona, persona_id) is None:
            s.add(Persona(persona_id=persona_id, display_name="JARVIS"))


def test_kst_bucketing_lands_in_local_hour(isolated_db):
    """A session at UTC 00:30 must bucket as KST hour=9 (not hour=0)."""

    init_db()
    _seed_user()
    _seed_persona()

    # 4 Tuesdays in a row, each at KST 09:30 (= UTC 00:30)
    base = datetime(2026, 5, 26, 9, 30)  # Tue 2026-05-26 09:30 KST
    with get_session() as s:
        for i in range(4):
            s.add(
                ChatSession(
                    session_id=f"tue-{i}",
                    user_id="sir",
                    persona_id="jarvis",
                    started_at=_utc(base + timedelta(weeks=i)),
                )
            )

    window_start = _utc(base) - timedelta(days=1)
    with get_session() as s:
        obs = time_based.detect(s, "sir", window_start, "Asia/Seoul")

    assert len(obs) == 1
    o = obs[0]
    # Tuesday = 1 (Mon=0). Hour 9 = local KST hour.
    assert o.weekday == 1
    assert o.hour == 9
    assert o.occurrences == 4
    assert o.opportunities == 4


def test_partial_consistency_tuesdays(isolated_db):
    """If sir was active on 4 Tuesdays but only 3 had a 9am session: 3/4."""

    init_db()
    _seed_user()
    _seed_persona()

    # 4 Tuesdays. 3 of them have 9am sessions; the 4th has a 16:00
    # session instead (so sir was engaged that Tuesday — the
    # denominator includes it — but the 9am bucket misses).
    tuesdays = [datetime(2026, 5, 26) + timedelta(weeks=i) for i in range(4)]
    with get_session() as s:
        for i, t in enumerate(tuesdays):
            hour = 9 if i < 3 else 16
            s.add(
                ChatSession(
                    session_id=f"tue-{i}",
                    user_id="sir",
                    persona_id="jarvis",
                    started_at=_utc(t.replace(hour=hour, minute=5)),
                )
            )

    window_start = _utc(tuesdays[0]) - timedelta(days=1)
    with get_session() as s:
        obs = time_based.detect(s, "sir", window_start, "Asia/Seoul")

    # Two buckets: (Tue, 9) and (Tue, 16).
    by_bucket = {(o.weekday, o.hour): o for o in obs}
    assert (1, 9) in by_bucket and (1, 16) in by_bucket

    nine = by_bucket[(1, 9)]
    assert nine.occurrences == 3
    assert nine.opportunities == 4
    ratio = nine.occurrences / nine.opportunities
    assert ratio == pytest.approx(0.75)


def test_no_sessions_no_observations(isolated_db):
    init_db()
    _seed_user()
    _seed_persona()
    with get_session() as s:
        obs = time_based.detect(
            s,
            "sir",
            datetime(2026, 5, 1),
            "Asia/Seoul",
        )
    assert obs == []


def test_window_excludes_old_sessions(isolated_db):
    """Sessions older than window_start must not be counted."""

    init_db()
    _seed_user()
    _seed_persona()

    old = datetime(2026, 1, 1, 9, 5)
    recent = datetime(2026, 5, 26, 9, 5)
    with get_session() as s:
        s.add(
            ChatSession(
                session_id="old",
                user_id="sir",
                persona_id="jarvis",
                started_at=_utc(old),
            )
        )
        s.add(
            ChatSession(
                session_id="recent",
                user_id="sir",
                persona_id="jarvis",
                started_at=_utc(recent),
            )
        )

    window_start = _utc(datetime(2026, 5, 1))
    with get_session() as s:
        obs = time_based.detect(s, "sir", window_start, "Asia/Seoul")

    # Only the recent session is visible
    assert sum(o.occurrences for o in obs) == 1
    assert sum(o.opportunities for o in obs) == 1


def test_user_isolation(isolated_db):
    """gf's sessions don't bleed into sir's pattern."""

    init_db()
    _seed_user("sir")
    _seed_user("gf")
    _seed_persona()

    base = datetime(2026, 5, 26, 9, 5)
    with get_session() as s:
        for i in range(3):
            s.add(
                ChatSession(
                    session_id=f"gf-{i}",
                    user_id="gf",
                    persona_id="jarvis",
                    started_at=_utc(base + timedelta(weeks=i)),
                )
            )

    window_start = _utc(datetime(2026, 5, 1))
    with get_session() as s:
        obs_sir = time_based.detect(s, "sir", window_start, "Asia/Seoul")
        obs_gf = time_based.detect(s, "gf", window_start, "Asia/Seoul")

    assert obs_sir == []
    assert sum(o.occurrences for o in obs_gf) == 3
