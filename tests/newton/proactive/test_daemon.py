"""Tests for newton.proactive.daemon and the proactive CLI."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy import select

from newton.cli import cli
from newton.db import get_session, init_db
from newton.models.system_metric import SystemMetric
from newton.proactive.daemon import ProactiveDaemon
from newton.proactive.monitors import Monitor
from newton.proactive.pidfile import (
    clear_pidfile,
    inspect,
    pidfile_path,
    read_pidfile,
    write_pidfile,
)

# ── Tiny in-test monitors ───────────────────────────────────────────────────


class _FixedMonitor(Monitor):
    """Always reports the same value, for deterministic assertions."""

    name = "fixed"
    metric_type = "cpu"

    def __init__(self, value: float | None = 42.0) -> None:
        self._value = value

    def sample(self) -> float | None:
        return self._value


class _UnavailableMonitor(Monitor):
    """Always None — the daemon should write zero rows for it."""

    name = "unavailable"
    metric_type = "memory"

    def sample(self) -> float | None:
        return None


class _ExplodingMonitor(Monitor):
    """Raises on sample — the daemon must keep running."""

    name = "explody"
    metric_type = "network"

    def sample(self) -> float | None:
        raise RuntimeError("boom")


# ── tick_once ───────────────────────────────────────────────────────────────


def test_tick_once_writes_one_row_per_available_monitor(isolated_db):
    init_db()
    daemon = ProactiveDaemon(
        monitors=[_FixedMonitor(value=10.0), _UnavailableMonitor()],
        is_active=lambda: True,
    )

    report = daemon.tick_once()

    assert report.metrics_written == 1
    assert report.metrics_skipped == 1
    assert report.per_monitor == {"fixed": 10.0, "unavailable": None}

    with get_session() as session:
        rows = session.execute(select(SystemMetric)).scalars().all()
    assert len(rows) == 1
    assert rows[0].metric_type == "cpu"
    assert rows[0].value == pytest.approx(10.0)


def test_tick_once_survives_monitor_exception(isolated_db):
    init_db()
    daemon = ProactiveDaemon(
        monitors=[_FixedMonitor(value=1.0), _ExplodingMonitor()],
        is_active=lambda: True,
    )

    report = daemon.tick_once()

    assert report.metrics_written == 1
    assert report.metrics_skipped == 1
    assert report.per_monitor["explody"] is None


# ── next_interval ───────────────────────────────────────────────────────────


def test_next_interval_picks_active_when_active():
    d = ProactiveDaemon(
        monitors=[_FixedMonitor()],
        is_active=lambda: True,
        active_interval_s=5.0,
        idle_interval_s=60.0,
    )
    assert d.next_interval() == 5.0


def test_next_interval_picks_idle_when_idle():
    d = ProactiveDaemon(
        monitors=[_FixedMonitor()],
        is_active=lambda: False,
        active_interval_s=5.0,
        idle_interval_s=60.0,
    )
    assert d.next_interval() == 60.0


def test_next_interval_falls_back_to_idle_when_predicate_raises():
    def _broken() -> bool:
        raise RuntimeError("db down")

    d = ProactiveDaemon(
        monitors=[_FixedMonitor()],
        is_active=_broken,
        active_interval_s=5.0,
        idle_interval_s=30.0,
    )
    assert d.next_interval() == 30.0


# ── run_forever / shutdown ──────────────────────────────────────────────────


def test_run_forever_exits_promptly_on_stop(isolated_db):
    """Stopping mid-sleep returns within roughly one shutdown slice."""

    init_db()
    daemon = ProactiveDaemon(
        monitors=[_FixedMonitor(value=7.0)],
        is_active=lambda: False,
        active_interval_s=5.0,
        idle_interval_s=30.0,
        shutdown_slice_s=0.1,
    )

    thread = threading.Thread(target=daemon.run_forever, daemon=True)
    thread.start()

    # Let one tick land so we know the loop is active.
    time.sleep(0.3)
    started = time.monotonic()
    daemon.stop()
    thread.join(timeout=2.0)
    elapsed = time.monotonic() - started

    assert not thread.is_alive(), "daemon thread did not exit after stop()"
    # Slice is 0.1s; allow some scheduling slack but well under one interval.
    assert elapsed < 1.0, f"shutdown took {elapsed:.2f}s, expected ~slice"

    with get_session() as session:
        rows = (
            session.execute(
                select(SystemMetric).where(SystemMetric.metric_type == "cpu")
            )
            .scalars()
            .all()
        )
    assert len(rows) >= 1, "expected at least one sample row"


# ── pidfile ─────────────────────────────────────────────────────────────────


def test_pidfile_inspect_missing(tmp_path):
    path = tmp_path / "absent.pid"
    s = inspect(path)
    assert s.pid is None
    assert s.running is False
    assert s.stale is False


def test_pidfile_inspect_alive(tmp_path):
    path = tmp_path / "live.pid"
    write_pidfile(path, pid=os.getpid())
    s = inspect(path)
    assert s.pid == os.getpid()
    assert s.running is True
    assert s.stale is False
    clear_pidfile(path)


def test_pidfile_inspect_stale(tmp_path, monkeypatch):
    path = tmp_path / "stale.pid"
    write_pidfile(path, pid=999_999)  # impossibly high

    def _no_process(pid, sig):  # noqa: ARG001
        raise ProcessLookupError

    monkeypatch.setattr(os, "kill", _no_process)
    s = inspect(path)
    assert s.pid == 999_999
    assert s.running is False
    assert s.stale is True


def test_pidfile_read_garbage_returns_none(tmp_path):
    path = tmp_path / "garbage.pid"
    path.write_text("not-a-number\n", encoding="utf-8")
    assert read_pidfile(path) is None


# ── CLI: proactive status ───────────────────────────────────────────────────


def test_cli_status_reports_no_samples_on_fresh_db(isolated_db):
    init_db()
    runner = CliRunner()
    result = runner.invoke(cli, ["proactive", "status", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["running"] is False
    assert payload["samples_total"] == 0
    assert payload["samples_per_type"] == {}
    assert payload["last_sample_at"] is None


def test_cli_status_reports_sample_counts(isolated_db):
    init_db()
    with get_session() as session:
        session.add(SystemMetric(metric_type="cpu", value=12.0))
        session.add(SystemMetric(metric_type="cpu", value=15.0))
        session.add(SystemMetric(metric_type="memory", value=40.0))

    runner = CliRunner()
    result = runner.invoke(cli, ["proactive", "status", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["samples_total"] == 3
    assert payload["samples_per_type"] == {"cpu": 2, "memory": 1}
    assert payload["last_sample_at"] is not None


# ── CLI: proactive start --once ────────────────────────────────────────────


def test_cli_start_once_writes_rows(isolated_db, monkeypatch):
    init_db()

    # Replace default monitors with a fixed set so the test doesn't depend
    # on the host's GPU/battery presence. ProactiveDaemon imports
    # default_monitors at module load, so the patch must target the
    # daemon module's namespace, not the monitors package.
    monkeypatch.setattr(
        "newton.proactive.daemon.default_monitors",
        lambda: [_FixedMonitor(value=99.0)],
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["proactive", "start", "--once", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["metrics_written"] == 1
    assert payload["per_monitor"] == {"fixed": 99.0}

    with get_session() as session:
        rows = session.execute(select(SystemMetric)).scalars().all()
    assert len(rows) == 1
    assert rows[0].value == pytest.approx(99.0)


# ── CLI: stop with no daemon ───────────────────────────────────────────────


def test_cli_stop_when_not_running(isolated_db):
    init_db()
    runner = CliRunner()
    result = runner.invoke(cli, ["proactive", "stop", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["stopped"] is False
    assert payload["reason"] == "no pidfile"


def test_cli_stop_clears_stale_pidfile(isolated_db):
    init_db()
    # Write a PID for a process that definitely isn't running.
    pidpath: Path = pidfile_path(Path(os.environ["NEWTON_DATA_DIR"]))
    write_pidfile(pidpath, pid=999_999)

    runner = CliRunner()
    result = runner.invoke(cli, ["proactive", "stop", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["stopped"] is False
    assert payload["reason"] == "stale pidfile cleared"
    assert not pidpath.exists()
