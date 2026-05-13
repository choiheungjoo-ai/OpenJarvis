"""CLI integration tests for ``newton init / seed / personas list / users list``.

We use :mod:`click.testing.CliRunner` so each test is self-contained — no
subprocess spawning, no .venv assumption.  The database lives in a
per-test ``tmp_path`` directory via ``NEWTON_DATA_DIR``.

The ``--json`` outputs are validated programmatically; the human-readable
outputs are only checked for the presence of key tokens (so cosmetic
changes don't break the suite).
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from newton.cli import cli
from newton.db import get_engine


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Point Newton at a fresh DB inside ``tmp_path`` for the duration of one test."""
    monkeypatch.setenv("NEWTON_DATA_DIR", str(tmp_path))
    # Reset *both* cached singletons so the next call rebuilds an engine
    # bound to the new NEWTON_DATA_DIR.  Forgetting _session_factory leaks
    # the previous test's engine into this test's session, which silently
    # talks to the prior DB.
    from newton.db import _session_factory

    get_engine.cache_clear()
    _session_factory.cache_clear()
    yield tmp_path
    get_engine.cache_clear()
    _session_factory.cache_clear()


@pytest.fixture
def runner():
    return CliRunner()


# ─────────────────────────────────────────────────────────────────────────────
# init  (migrate + seed in one shot)
# ─────────────────────────────────────────────────────────────────────────────


def test_init_creates_db_and_seeds_everything(runner, isolated_db):
    result = runner.invoke(cli, ["init", "--json"])
    assert result.exit_code == 0, result.output

    data = json.loads(result.output)
    assert data["migrations_applied"] == [1]
    assert sorted(data["personas_added"]) == ["butler", "friday", "jarvis"]
    assert sorted(data["users_added"]) == ["gf", "sir"]
    assert sorted(data["links_added"]) == [["gf", "friday"], ["sir", "jarvis"]]


def test_init_is_idempotent(runner, isolated_db):
    runner.invoke(cli, ["init", "--json"])
    result = runner.invoke(cli, ["init", "--json"])
    assert result.exit_code == 0

    data = json.loads(result.output)
    assert data["migrations_applied"] == []
    assert data["personas_added"] == []
    assert data["users_added"] == []
    assert data["links_added"] == []


def test_init_human_output_mentions_personas_and_users(runner, isolated_db):
    """Cosmetic check — exact strings may shift, just look for the key tokens."""
    result = runner.invoke(cli, ["init"])
    assert result.exit_code == 0
    out = result.output
    # We don't pin the wording, but the user-facing output should at least
    # mention the things that got inserted.
    assert "butler" in out
    assert "jarvis" in out
    assert "friday" in out
    assert "sir" in out
    assert "gf" in out


# ─────────────────────────────────────────────────────────────────────────────
# seed  (without migrate — but db must already exist)
# ─────────────────────────────────────────────────────────────────────────────


def test_seed_after_migrate_works(runner, isolated_db):
    # migrate first, then seed separately
    r1 = runner.invoke(cli, ["db", "migrate", "--json"])
    assert r1.exit_code == 0

    r2 = runner.invoke(cli, ["seed", "--json"])
    assert r2.exit_code == 0
    data = json.loads(r2.output)
    assert sorted(data["personas_added"]) == ["butler", "friday", "jarvis"]
    assert sorted(data["users_added"]) == ["gf", "sir"]


def test_seed_is_idempotent(runner, isolated_db):
    runner.invoke(cli, ["init", "--json"])
    result = runner.invoke(cli, ["seed", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["personas_added"] == []
    assert data["users_added"] == []


# ─────────────────────────────────────────────────────────────────────────────
# personas list  (json + human)
# ─────────────────────────────────────────────────────────────────────────────


def test_personas_list_json_after_seed(runner, isolated_db):
    runner.invoke(cli, ["init", "--json"])

    result = runner.invoke(cli, ["personas", "list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 3
    by_id = {p["persona_id"]: p for p in data}

    assert by_id["butler"]["is_public"] is True
    assert by_id["butler"]["is_default"] is True
    assert by_id["butler"]["owner_user_id"] is None
    assert by_id["butler"]["owner_display_name"] is None

    assert by_id["jarvis"]["owner_user_id"] == "sir"
    assert by_id["jarvis"]["owner_display_name"] == "Alex"
    assert by_id["jarvis"]["is_public"] is False

    assert by_id["friday"]["owner_user_id"] == "gf"
    assert by_id["friday"]["owner_display_name"] == "Stella"


def test_personas_list_human_shows_owner_display_name(runner, isolated_db):
    """Block-1.md requires 'owner: Alex' (not 'owner: sir') in human output."""
    runner.invoke(cli, ["init", "--json"])
    result = runner.invoke(cli, ["personas", "list"])
    assert result.exit_code == 0
    assert "owner: Alex" in result.output
    assert "owner: Stella" in result.output
    # Butler line should show public + default
    assert "public" in result.output
    assert "default" in result.output


def test_personas_list_empty_before_seed(runner, isolated_db):
    runner.invoke(cli, ["db", "migrate", "--json"])
    result = runner.invoke(cli, ["personas", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == []


# ─────────────────────────────────────────────────────────────────────────────
# users list
# ─────────────────────────────────────────────────────────────────────────────


def test_users_list_json_after_seed(runner, isolated_db):
    runner.invoke(cli, ["init", "--json"])

    result = runner.invoke(cli, ["users", "list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 2
    by_id = {u["user_id"]: u for u in data}

    assert by_id["sir"]["display_name"] == "Alex"
    assert by_id["sir"]["default_persona_id"] == "jarvis"
    assert by_id["sir"]["retry_profile"] == "normal"

    assert by_id["gf"]["display_name"] == "Stella"
    assert by_id["gf"]["default_persona_id"] == "friday"


def test_users_list_human(runner, isolated_db):
    runner.invoke(cli, ["init", "--json"])
    result = runner.invoke(cli, ["users", "list"])
    assert result.exit_code == 0
    out = result.output
    assert "sir" in out and "Alex" in out and "jarvis" in out
    assert "gf" in out and "Stella" in out and "friday" in out
