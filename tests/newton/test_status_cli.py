"""Tests for ``newton status``.

Status is read-only, so the surface area is small:
    * Empty DB    — reports 'not initialized' state without crashing.
    * After init  — reports 3 personas, 2 users, schema up to date.
    * --json out  — stable JSON shape, all expected keys present.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from newton.cli import cli
from newton.db import _session_factory, get_engine


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWTON_DATA_DIR", str(tmp_path))
    get_engine.cache_clear()
    _session_factory.cache_clear()
    yield tmp_path
    get_engine.cache_clear()
    _session_factory.cache_clear()


@pytest.fixture
def runner():
    return CliRunner()


# ─────────────────────────────────────────────────────────────────────────────
# Empty DB
# ─────────────────────────────────────────────────────────────────────────────


def test_status_on_fresh_dir_does_not_crash(runner, isolated_db):
    """No DB file, no migrations applied — status should still succeed."""
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Newton" in out
    assert "Database" in out
    assert "Personas" in out
    assert "Users" in out
    assert "Config" in out


def test_status_json_on_fresh_dir(runner, isolated_db):
    result = runner.invoke(cli, ["status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)

    assert "version" in data
    assert data["database"]["migrations_applied"] == []
    assert data["database"]["schema_up_to_date"] is False
    assert data["personas"] == []
    assert data["users"] == []
    assert data["config"]["active_profile"] == "normal"


# ─────────────────────────────────────────────────────────────────────────────
# After init
# ─────────────────────────────────────────────────────────────────────────────


def test_status_after_init_shows_seeded_data(runner, isolated_db):
    init_res = runner.invoke(cli, ["init", "--json"])
    assert init_res.exit_code == 0

    result = runner.invoke(cli, ["status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)

    assert data["database"]["migrations_applied"] == [1]
    assert data["database"]["schema_up_to_date"] is True
    assert data["database"]["size_bytes"] > 0

    persona_ids = {p["persona_id"] for p in data["personas"]}
    assert persona_ids == {"butler", "jarvis", "friday"}

    user_ids = {u["user_id"] for u in data["users"]}
    assert user_ids == {"sir", "gf"}

    # owner_display_name resolution
    by_pid = {p["persona_id"]: p for p in data["personas"]}
    assert by_pid["jarvis"]["owner_display_name"] == "Alex"
    assert by_pid["friday"]["owner_display_name"] == "Stella"


def test_status_human_output_after_init_mentions_key_facts(runner, isolated_db):
    runner.invoke(cli, ["init", "--json"])
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0
    out = result.output

    # Database section
    assert "up to date" in out

    # Personas section — must show all three with their right owners.
    assert "butler" in out and "public" in out
    assert "jarvis" in out and "Alex" in out
    assert "friday" in out and "Stella" in out

    # Users section
    assert "sir" in out
    assert "gf" in out

    # Config section
    assert "normal" in out  # active_profile


# ─────────────────────────────────────────────────────────────────────────────
# Migrations only (no seed)
# ─────────────────────────────────────────────────────────────────────────────


def test_status_after_migrate_only_shows_empty_personas(runner, isolated_db):
    """``db migrate`` without ``seed`` leaves the DB schema-ready but empty."""
    runner.invoke(cli, ["db", "migrate", "--json"])

    result = runner.invoke(cli, ["status", "--json"])
    data = json.loads(result.output)

    assert data["database"]["schema_up_to_date"] is True
    assert data["personas"] == []
    assert data["users"] == []
