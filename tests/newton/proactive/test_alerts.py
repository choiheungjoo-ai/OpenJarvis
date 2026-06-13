"""Tests for newton.proactive.alerts — threshold checker + display helper.

Hard requirement enforced here: the ``[kind]`` prefix on
``proactive_notifications.notification_text`` is storage-only. It must
never appear in user-facing text, so every assertion that touches user
output goes through :func:`display_text` and checks the prefix is
absent.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from click.testing import CliRunner
from sqlalchemy import select

from newton.cli import cli
from newton.db import get_session, init_db
from newton.models.proactive_notification import ProactiveNotification
from newton.models.system_metric import SystemMetric
from newton.proactive.alerts import (
    AlertChecker,
    display_text,
    extract_kind,
)
from newton.proactive.config import ProactiveConfig, ThresholdRule

# ── helpers ────────────────────────────────────────────────────────────────


def _config(rules: list[ThresholdRule], cooldown_minutes: int = 15) -> ProactiveConfig:
    return ProactiveConfig(thresholds=rules, cooldown_minutes=cooldown_minutes)


def _rule(
    kind: str,
    metric_type: str,
    op: str,
    value: float,
    text: str = "{value:.0f}",
    dormant: bool = False,
) -> ThresholdRule:
    return ThresholdRule(
        kind=kind,
        metric_type=metric_type,
        op=op,
        value=value,
        text=text,
        dormant=dormant,
    )


def _seed_metric(metric_type: str, value: float) -> None:
    with get_session() as session:
        session.add(SystemMetric(metric_type=metric_type, value=value))


def _seed_user(user_id: str = "sir") -> None:
    """Insert a stand-alone user — alert rows FK to users(user_id)."""

    from newton.models.user import User

    with get_session() as session:
        if session.get(User, user_id) is None:
            session.add(User(user_id=user_id, display_name=user_id.title()))


# ── display_text / extract_kind ─────────────────────────────────────────────


def test_display_text_strips_kind_prefix():
    stored = "[cpu_high] Sir, CPU at 95%."
    shown = display_text(stored)
    assert shown == "Sir, CPU at 95%."
    # Belt-and-suspenders: the prefix really is gone.
    assert "[cpu_high]" not in shown
    assert "[" not in shown[:1]  # no leading bracket


def test_display_text_passes_through_unprefixed_text():
    """A row written by some other code path (no prefix) is unchanged."""

    raw = "Sir, your meeting starts in 10 minutes."
    assert display_text(raw) == raw


def test_extract_kind_roundtrip():
    assert extract_kind("[battery_low] Sir, battery at 18%.") == "battery_low"
    assert extract_kind("no prefix here") is None
    assert extract_kind("[BadKind] uppercase rejected") is None  # alphabet mismatch


# ── single-rule firing ─────────────────────────────────────────────────────


def test_rule_fires_when_threshold_crossed(isolated_db):
    init_db()
    _seed_user()
    _seed_metric("cpu", 95.0)

    checker = AlertChecker(
        config=_config(
            [_rule("cpu_high", "cpu", ">", 90.0, "Sir, CPU at {value:.0f}%.")]
        )
    )
    with get_session() as session:
        fired = checker.run(session, "sir")

    assert len(fired) == 1
    a = fired[0]
    assert a.kind == "cpu_high"
    assert a.value == pytest.approx(95.0)

    # Stored row carries the prefix; user-facing display does NOT.
    assert a.stored_text == "[cpu_high] Sir, CPU at 95%."
    assert a.display == "Sir, CPU at 95%."
    assert "[cpu_high]" not in a.display


def test_rule_does_not_fire_below_threshold(isolated_db):
    init_db()
    _seed_user()
    _seed_metric("cpu", 50.0)

    checker = AlertChecker(config=_config([_rule("cpu_high", "cpu", ">", 90.0)]))
    with get_session() as session:
        fired = checker.run(session, "sir")
    assert fired == []


def test_lt_operator_for_battery(isolated_db):
    init_db()
    _seed_user()
    _seed_metric("battery", 18.0)

    checker = AlertChecker(
        config=_config(
            [
                _rule("battery_low", "battery", "<", 20.0, "battery {value:.0f}"),
                _rule("battery_crit", "battery", "<", 10.0, "battery crit"),
            ]
        )
    )
    with get_session() as session:
        fired = checker.run(session, "sir")
    kinds = [a.kind for a in fired]
    assert kinds == ["battery_low"]  # critical does NOT fire at 18%


def test_battery_low_and_critical_fire_independently(isolated_db):
    init_db()
    _seed_user()
    _seed_metric("battery", 5.0)  # crosses both thresholds

    checker = AlertChecker(
        config=_config(
            [
                _rule("battery_low", "battery", "<", 20.0, "battery {value:.0f}"),
                _rule("battery_crit", "battery", "<", 10.0, "battery crit"),
            ]
        )
    )
    with get_session() as session:
        fired = checker.run(session, "sir")

    kinds = sorted(a.kind for a in fired)
    assert kinds == ["battery_crit", "battery_low"]


def test_missing_metric_type_skipped_without_error(isolated_db):
    """A rule for a metric_type we have no samples of must not raise."""

    init_db()
    _seed_user()
    # No memory samples in this DB.

    checker = AlertChecker(config=_config([_rule("memory_high", "memory", ">", 80.0)]))
    with get_session() as session:
        fired = checker.run(session, "sir")
    assert fired == []


def test_dormant_rule_never_fires(isolated_db):
    init_db()
    _seed_user()
    _seed_metric("network", 1.0)  # would cross a "< 50" rule

    checker = AlertChecker(
        config=_config([_rule("network_slow", "network", "<", 50.0, dormant=True)])
    )
    with get_session() as session:
        fired = checker.run(session, "sir")
    assert fired == []


# ── cooldown ───────────────────────────────────────────────────────────────


def test_cooldown_suppresses_second_fire_within_window(isolated_db):
    init_db()
    _seed_user()
    _seed_metric("cpu", 95.0)

    checker = AlertChecker(
        config=_config(
            [_rule("cpu_high", "cpu", ">", 90.0)],
            cooldown_minutes=15,
        )
    )
    now = datetime(2026, 6, 14, 12, 0, 0)
    with get_session() as session:
        first = checker.run(session, "sir", now=now)
        # Add a fresh sample so the checker sees current data again.
        session.add(SystemMetric(metric_type="cpu", value=96.0))
        session.flush()
        second = checker.run(session, "sir", now=now + timedelta(minutes=14))
    assert len(first) == 1
    assert second == [], "cooldown should suppress the second fire"


def test_cooldown_expires(isolated_db):
    init_db()
    _seed_user()
    _seed_metric("cpu", 95.0)

    checker = AlertChecker(
        config=_config(
            [_rule("cpu_high", "cpu", ">", 90.0)],
            cooldown_minutes=15,
        )
    )
    now = datetime(2026, 6, 14, 12, 0, 0)
    with get_session() as session:
        first = checker.run(session, "sir", now=now)
        session.add(SystemMetric(metric_type="cpu", value=96.0))
        session.flush()
        third = checker.run(session, "sir", now=now + timedelta(minutes=16))
    assert len(first) == 1
    assert len(third) == 1, "should fire again past the cooldown window"


def test_zero_cooldown_means_no_cooldown(isolated_db):
    init_db()
    _seed_user()
    _seed_metric("cpu", 95.0)

    checker = AlertChecker(
        config=_config(
            [_rule("cpu_high", "cpu", ">", 90.0)],
            cooldown_minutes=0,
        )
    )
    now = datetime(2026, 6, 14, 12, 0, 0)
    with get_session() as session:
        first = checker.run(session, "sir", now=now)
        session.add(SystemMetric(metric_type="cpu", value=96.0))
        session.flush()
        second = checker.run(session, "sir", now=now)
    assert len(first) == 1
    assert len(second) == 1


def test_cooldown_is_per_user(isolated_db):
    """User A's cooldown for cpu_high doesn't suppress user B's."""

    init_db()
    _seed_user("sir")
    _seed_user("gf")
    _seed_metric("cpu", 95.0)

    checker = AlertChecker(
        config=_config(
            [_rule("cpu_high", "cpu", ">", 90.0)],
            cooldown_minutes=15,
        )
    )
    now = datetime(2026, 6, 14, 12, 0, 0)
    with get_session() as session:
        a = checker.run(session, "sir", now=now)
        b = checker.run(session, "gf", now=now)
    assert len(a) == 1
    assert len(b) == 1


# ── DB-side bookkeeping ────────────────────────────────────────────────────


def test_rows_inserted_with_prefix_and_correct_user(isolated_db):
    init_db()
    _seed_user()
    _seed_metric("cpu", 95.0)

    checker = AlertChecker(config=_config([_rule("cpu_high", "cpu", ">", 90.0)]))
    with get_session() as session:
        checker.run(session, "sir")

    with get_session() as session:
        rows = session.execute(select(ProactiveNotification)).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == "sir"
    # Storage form has the prefix.
    assert row.notification_text.startswith("[cpu_high] ")
    # Implicit "pending" via response columns.
    assert row.user_response is None
    assert row.response_at is None
    # And the user-facing rendering strips the prefix.
    assert (
        display_text(row.notification_text) == row.notification_text.split("] ", 1)[1]
    )
    assert "[" not in display_text(row.notification_text)[:1]


# ── CLI: proactive test-alert ──────────────────────────────────────────────


def test_cli_test_alert_writes_row_and_returns_clean_text(isolated_db, monkeypatch):
    """The CLI must surface display_text only — never the stored prefix."""

    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(_repo_config_dir()))
    init_db()
    _seed_user()

    runner = CliRunner()
    result = runner.invoke(
        cli, ["proactive", "test-alert", "battery_low", "--user", "sir", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert payload["fired"] is True
    assert len(payload["alerts"]) >= 1
    a = next(x for x in payload["alerts"] if x["kind"] == "battery_low")
    # The CLI's "text" field is the user-facing string. The prefix
    # must not be in it.
    assert "[battery_low]" not in a["text"]
    assert a["text"].startswith("Sir, battery at")

    with get_session() as session:
        rows = session.execute(select(ProactiveNotification)).scalars().all()
    assert len(rows) == 1
    # The stored form DOES carry the prefix — that's the whole point.
    assert rows[0].notification_text.startswith("[battery_low] ")


def test_cli_test_alert_unknown_kind(isolated_db, monkeypatch):
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(_repo_config_dir()))
    init_db()
    _seed_user()

    runner = CliRunner()
    result = runner.invoke(cli, ["proactive", "test-alert", "nope", "--user", "sir"])
    assert result.exit_code == 1
    assert "no rule with kind='nope'" in result.output


def test_cli_test_alert_dormant_rule_refused(isolated_db, monkeypatch):
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(_repo_config_dir()))
    init_db()
    _seed_user()

    runner = CliRunner()
    # network_slow is dormant in the shipped yaml.
    result = runner.invoke(
        cli, ["proactive", "test-alert", "network_slow", "--user", "sir"]
    )
    assert result.exit_code == 1
    assert "dormant" in result.output


def test_cli_test_alert_cooldown_then_force(isolated_db, monkeypatch):
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(_repo_config_dir()))
    init_db()
    _seed_user()
    runner = CliRunner()

    first = runner.invoke(
        cli, ["proactive", "test-alert", "battery_low", "--user", "sir", "--json"]
    )
    assert first.exit_code == 0
    assert json.loads(first.output)["fired"] is True

    second = runner.invoke(
        cli, ["proactive", "test-alert", "battery_low", "--user", "sir", "--json"]
    )
    payload2 = json.loads(second.output)
    assert payload2["fired"] is False
    assert "cooldown" in payload2.get("reason", "")

    forced = runner.invoke(
        cli,
        [
            "proactive",
            "test-alert",
            "battery_low",
            "--user",
            "sir",
            "--ignore-cooldown",
            "--json",
        ],
    )
    assert json.loads(forced.output)["fired"] is True


# ── repo config path helper ────────────────────────────────────────────────


def _repo_config_dir():
    """Absolute path to the repo's ``config/`` directory."""
    from pathlib import Path

    here = Path(__file__).resolve()
    # tests/newton/proactive/test_alerts.py → repo root
    return here.parent.parent.parent.parent / "config"
