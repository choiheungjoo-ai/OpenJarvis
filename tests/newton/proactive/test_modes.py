"""Tests for proactive mode resolution + time-bounded reverts."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from click.testing import CliRunner

from newton.cli import cli
from newton.db import get_session, init_db
from newton.models.user import User
from newton.proactive.modes import (
    VALID_MODES,
    apply_revert_due,
    list_modes,
    resolve_mode,
    set_mode,
)


def _seed_user(user_id: str = "sir") -> None:
    with get_session() as s:
        if s.get(User, user_id) is None:
            s.add(User(user_id=user_id, display_name="Sir"))


# ── migration sanity ──────────────────────────────────────────────────────


def test_migration_010_applies_and_columns_default(isolated_db):
    init_db()
    _seed_user()
    with get_session() as s:
        u = s.get(User, "sir")
    assert u.proactive_mode == "smart"
    assert u.proactive_mode_revert_at is None


# ── resolve_mode ─────────────────────────────────────────────────────────


def test_resolve_returns_stored_mode(isolated_db):
    init_db()
    _seed_user()
    with get_session() as s:
        u = s.get(User, "sir")
        u.proactive_mode = "aggressive"
    with get_session() as s:
        r = resolve_mode(s, "sir")
    assert r.mode == "aggressive"
    assert r.reverted_now is False


def test_resolve_heals_expired_revert(isolated_db):
    init_db()
    _seed_user()
    with get_session() as s:
        u = s.get(User, "sir")
        u.proactive_mode = "off"
        u.proactive_mode_revert_at = datetime(2026, 6, 14, 10, 0, 0)
    # now is 1 hour after the revert_at
    with get_session() as s:
        r = resolve_mode(s, "sir", now=datetime(2026, 6, 14, 11, 0, 0))
    assert r.mode == "smart"
    assert r.reverted_now is True
    # Persistence: the heal landed in the DB.
    with get_session() as s:
        u = s.get(User, "sir")
    assert u.proactive_mode == "smart"
    assert u.proactive_mode_revert_at is None


def test_resolve_keeps_future_revert_intact(isolated_db):
    init_db()
    _seed_user()
    future = datetime(2030, 1, 1)
    with get_session() as s:
        u = s.get(User, "sir")
        u.proactive_mode = "off"
        u.proactive_mode_revert_at = future
    with get_session() as s:
        r = resolve_mode(s, "sir", now=datetime(2026, 6, 14))
    assert r.mode == "off"
    assert r.reverted_now is False
    assert r.revert_at == future


def test_resolve_unknown_user_returns_default(isolated_db):
    init_db()
    with get_session() as s:
        r = resolve_mode(s, "ghost", default="minimal")
    assert r.mode == "minimal"
    assert r.reverted_now is False


# ── set_mode ─────────────────────────────────────────────────────────────


def test_set_mode_permanent(isolated_db):
    init_db()
    _seed_user()
    with get_session() as s:
        r = set_mode(s, "sir", "aggressive")
    assert r.mode == "aggressive"
    assert r.revert_at is None
    with get_session() as s:
        u = s.get(User, "sir")
    assert u.proactive_mode == "aggressive"
    assert u.proactive_mode_revert_at is None


def test_set_mode_time_bounded(isolated_db):
    init_db()
    _seed_user()
    now = datetime(2026, 6, 14, 12, 0, 0)
    with get_session() as s:
        r = set_mode(s, "sir", "off", for_seconds=3600, now=now)
    assert r.revert_at == now + timedelta(hours=1)


def test_set_mode_invalid_mode(isolated_db):
    init_db()
    _seed_user()
    with pytest.raises(ValueError, match="mode must be"):
        with get_session() as s:
            set_mode(s, "sir", "unknown")


def test_set_mode_unknown_user(isolated_db):
    init_db()
    with pytest.raises(ValueError, match="unknown user"):
        with get_session() as s:
            set_mode(s, "ghost", "smart")


# ── apply_revert_due (batch) ─────────────────────────────────────────────


def test_apply_revert_due_heals_only_expired(isolated_db):
    init_db()
    _seed_user("sir")
    _seed_user("gf")
    now = datetime(2026, 6, 14, 12, 0, 0)
    with get_session() as s:
        sir = s.get(User, "sir")
        sir.proactive_mode = "off"
        sir.proactive_mode_revert_at = now - timedelta(minutes=5)  # expired
        gf = s.get(User, "gf")
        gf.proactive_mode = "aggressive"
        gf.proactive_mode_revert_at = now + timedelta(hours=1)  # future

    with get_session() as s:
        count = apply_revert_due(s, default="smart", now=now)
    assert count == 1

    with get_session() as s:
        sir = s.get(User, "sir")
        gf = s.get(User, "gf")
    assert sir.proactive_mode == "smart"
    assert sir.proactive_mode_revert_at is None
    assert gf.proactive_mode == "aggressive"


# ── list_modes ───────────────────────────────────────────────────────────


def test_list_modes_snapshots_every_user(isolated_db):
    init_db()
    _seed_user("sir")
    _seed_user("gf")
    with get_session() as s:
        gf = s.get(User, "gf")
        gf.proactive_mode = "minimal"
    with get_session() as s:
        out = list_modes(s)
    by_id = {m.user_id: m for m in out}
    assert by_id["sir"].mode == "smart"
    assert by_id["gf"].mode == "minimal"


# ── valid modes set ──────────────────────────────────────────────────────


def test_valid_modes_constant():
    assert set(VALID_MODES) == {"off", "minimal", "smart", "aggressive"}


# ── CLI ──────────────────────────────────────────────────────────────────


def test_cli_mode_change_permanent(seeded_db):
    runner = CliRunner()
    result = runner.invoke(
        cli, ["proactive", "mode", "aggressive", "--user", "sir", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["mode"] == "aggressive"
    assert payload["revert_at"] is None


def test_cli_mode_change_time_bounded(seeded_db):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "proactive",
            "mode",
            "off",
            "--user",
            "sir",
            "--for",
            "1h",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["mode"] == "off"
    assert payload["revert_at"] is not None


def test_cli_mode_show_current(seeded_db):
    runner = CliRunner()
    # No mode argument and no --list → shows current.
    result = runner.invoke(cli, ["proactive", "mode", "--user", "sir", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["mode"] == "smart"


def test_cli_mode_list(seeded_db):
    runner = CliRunner()
    result = runner.invoke(cli, ["proactive", "mode", "--list", "--json"])
    assert result.exit_code == 0
    rows = json.loads(result.output)
    ids = {r["user_id"] for r in rows}
    assert "sir" in ids
    assert "gf" in ids


def test_cli_mode_bad_duration(seeded_db):
    runner = CliRunner()
    result = runner.invoke(cli, ["proactive", "mode", "off", "--for", "purple"])
    assert result.exit_code == 1
    assert "--for" in result.output


def test_cli_mode_bad_mode(seeded_db):
    runner = CliRunner()
    result = runner.invoke(cli, ["proactive", "mode", "vroom"])
    assert result.exit_code == 1
    assert "must be one of" in result.output


# ── scheduler integration ───────────────────────────────────────────────


def test_scheduler_reads_stored_mode_when_passed_auto(isolated_db):
    """Passing mode='__auto__' to scheduler.tick resolves from the DB."""
    from newton.proactive.anticipation import AnticipationEngine
    from newton.proactive.config import (
        AnticipationConfig,
        ModeThresholds,
        QuietHoursConfig,
        SchedulerConfig,
    )
    from newton.proactive.scheduler import Scheduler

    init_db()
    _seed_user()
    with get_session() as s:
        u = s.get(User, "sir")
        u.proactive_mode = "off"

    sched = Scheduler(
        config=SchedulerConfig(
            max_per_tick=1,
            pattern_cooldown_minutes=30,
            quiet_hours=QuietHoursConfig(start="00:00", end="00:00"),
        ),
        engine=AnticipationEngine(
            config=AnticipationConfig(
                default_mode="smart",
                relevance_sigma_minutes=30,
                sequence_relevance_seconds=600,
                max_results=5,
                thresholds=ModeThresholds(),
            )
        ),
        tz_name="Asia/Seoul",
    )

    with get_session() as session:
        report = sched.tick(
            session,
            "sir",
            "__auto__",
            now=datetime(2026, 6, 14, 12, 0, 0),
        )
    assert report.mode == "off"
    assert report.reason == "mode=off"
