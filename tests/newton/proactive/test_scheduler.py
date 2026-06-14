"""Tests for the proactive scheduler."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from newton.db import get_session, init_db
from newton.models.proactive_notification import ProactiveNotification
from newton.models.tool_approval import ToolApproval
from newton.models.user import User
from newton.models.user_pattern import UserPattern
from newton.proactive.anticipation import AnticipationEngine
from newton.proactive.config import (
    AnticipationConfig,
    ModeThresholds,
    QuietHoursConfig,
    SchedulerConfig,
)
from newton.proactive.scheduler import Scheduler


def _seed_user(user_id: str = "sir") -> None:
    with get_session() as s:
        if s.get(User, user_id) is None:
            s.add(User(user_id=user_id, display_name="Sir"))


def _add_pattern(
    *, user_id: str, pattern_type: str, signature: dict, confidence: float
) -> int:
    with get_session() as s:
        row = UserPattern(
            user_id=user_id,
            pattern_type=pattern_type,
            pattern_data_json=json.dumps(
                signature, sort_keys=True, separators=(",", ":")
            ),
            confidence=confidence,
            occurrences=10,
            last_seen=datetime(2026, 6, 14, 0, 0, 0),
        )
        s.add(row)
        s.flush()
        return row.pattern_id


def _add_recent_run(
    *, user_id: str = "sir", tool: str = "vault_search", when: datetime
) -> None:
    with get_session() as s:
        s.add(
            ToolApproval(
                tool_name=tool,
                risk_level=1,
                user_id=user_id,
                decision="approved",
                decided_at=when,
            )
        )


CFG = SchedulerConfig(
    max_per_tick=1,
    pattern_cooldown_minutes=30,
    quiet_hours=QuietHoursConfig(start="23:00", end="07:00"),
)
ENGINE_CFG = AnticipationConfig(
    default_mode="smart",
    relevance_sigma_minutes=30.0,
    sequence_relevance_seconds=600,
    max_results=5,
    thresholds=ModeThresholds(),
)


def _kst_utc(dt_local: datetime) -> datetime:
    return (
        dt_local.replace(tzinfo=ZoneInfo("Asia/Seoul"))
        .astimezone(ZoneInfo("UTC"))
        .replace(tzinfo=None)
    )


def _scheduler() -> Scheduler:
    engine = AnticipationEngine(config=ENGINE_CFG)
    return Scheduler(config=CFG, engine=engine, tz_name="Asia/Seoul")


# ── happy path ────────────────────────────────────────────────────────────


def test_tick_writes_a_row_when_prediction_crosses_threshold(isolated_db):
    init_db()
    _seed_user()
    now = datetime(2026, 6, 14, 12, 0, 0)  # KST 21:00 — outside quiet hours
    pid = _add_pattern(
        user_id="sir",
        pattern_type="sequence",
        signature={
            "kind": "sequence",
            "after_tool": "vault_search",
            "then_tool": "vault_write",
            "within_seconds": 600,
        },
        confidence=0.9,
    )
    _add_recent_run(when=now - timedelta(minutes=2))

    sched = _scheduler()
    with get_session() as session:
        report = sched.tick(session, "sir", mode="smart", now=now)

    assert report.reason is None
    assert len(report.scheduled) == 1
    with get_session() as s:
        rows = list(s.execute(select(ProactiveNotification)).scalars().all())
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == "sir"
    assert row.trigger_pattern_id == pid
    assert row.notification_text.startswith("Sir,")
    # No [kind] prefix on scheduler-driven rows.
    assert "[" not in row.notification_text[:1]
    # Implicit pending: response columns still NULL.
    assert row.user_response is None
    assert row.response_at is None


# ── off mode short-circuits ──────────────────────────────────────────────


def test_off_mode_returns_reason_without_querying_predictions(isolated_db):
    init_db()
    _seed_user()
    sched = _scheduler()
    with get_session() as session:
        report = sched.tick(
            session, "sir", mode="off", now=datetime(2026, 6, 14, 12, 0, 0)
        )
    assert report.reason == "mode=off"
    assert report.scheduled == []


# ── quiet hours ──────────────────────────────────────────────────────────


def test_quiet_hours_blocks_non_urgent(isolated_db):
    init_db()
    _seed_user()
    _add_pattern(
        user_id="sir",
        pattern_type="sequence",
        signature={
            "kind": "sequence",
            "after_tool": "vault_search",
            "then_tool": "vault_write",
            "within_seconds": 600,
        },
        confidence=0.9,
    )

    # KST 02:00 → inside default 23:00-07:00 window
    now = _kst_utc(datetime(2026, 6, 14, 2, 0))
    _add_recent_run(when=now - timedelta(minutes=2))

    sched = _scheduler()
    with get_session() as session:
        report = sched.tick(session, "sir", mode="smart", now=now)
    assert report.reason == "quiet_hours"
    assert report.scheduled == []


def test_quiet_hours_bypassed_by_urgent(isolated_db):
    init_db()
    _seed_user()
    _add_pattern(
        user_id="sir",
        pattern_type="sequence",
        signature={
            "kind": "sequence",
            "after_tool": "vault_search",
            "then_tool": "vault_write",
            "within_seconds": 600,
        },
        confidence=0.9,
    )
    now = _kst_utc(datetime(2026, 6, 14, 2, 0))
    _add_recent_run(when=now - timedelta(minutes=2))

    sched = _scheduler()
    with get_session() as session:
        report = sched.tick(session, "sir", mode="smart", now=now, urgent=True)
    assert report.reason is None
    assert len(report.scheduled) == 1


# ── per-pattern cooldown ─────────────────────────────────────────────────


def test_pattern_cooldown_suppresses_second_tick(isolated_db):
    init_db()
    _seed_user()
    pid = _add_pattern(
        user_id="sir",
        pattern_type="sequence",
        signature={
            "kind": "sequence",
            "after_tool": "vault_search",
            "then_tool": "vault_write",
            "within_seconds": 600,
        },
        confidence=0.9,
    )

    now = datetime(2026, 6, 14, 12, 0, 0)
    _add_recent_run(when=now - timedelta(minutes=2))

    sched = _scheduler()
    with get_session() as session:
        first = sched.tick(session, "sir", mode="smart", now=now)
    assert len(first.scheduled) == 1

    # Second tick 5 minutes later — well within 30 min cooldown.
    _add_recent_run(when=now + timedelta(minutes=4))
    with get_session() as session:
        second = sched.tick(
            session, "sir", mode="smart", now=now + timedelta(minutes=5)
        )
    assert second.scheduled == []
    assert any(
        s["pattern_id"] == pid and s["reason"] == "pattern_cooldown"
        for s in second.skipped
    )


def test_pattern_cooldown_expires(isolated_db):
    init_db()
    _seed_user()
    _add_pattern(
        user_id="sir",
        pattern_type="sequence",
        signature={
            "kind": "sequence",
            "after_tool": "vault_search",
            "then_tool": "vault_write",
            "within_seconds": 600,
        },
        confidence=0.9,
    )

    now = datetime(2026, 6, 14, 12, 0, 0)
    _add_recent_run(when=now - timedelta(minutes=2))

    sched = _scheduler()
    with get_session() as session:
        first = sched.tick(session, "sir", mode="smart", now=now)
    assert len(first.scheduled) == 1

    later = now + timedelta(minutes=35)
    _add_recent_run(when=later - timedelta(minutes=2))
    with get_session() as session:
        third = sched.tick(session, "sir", mode="smart", now=later)
    assert len(third.scheduled) == 1


# ── no predictions → no rows ─────────────────────────────────────────────


def test_no_predictions_no_rows(isolated_db):
    init_db()
    _seed_user()
    sched = _scheduler()
    with get_session() as session:
        report = sched.tick(
            session, "sir", mode="smart", now=datetime(2026, 6, 14, 12, 0, 0)
        )
    assert report.reason is None
    assert report.scheduled == []
