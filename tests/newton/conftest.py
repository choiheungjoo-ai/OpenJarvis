"""Shared fixtures for newton tests."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from newton.db import get_engine


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Point Newton at a fresh DB inside tmp_path for one test."""
    monkeypatch.setenv("NEWTON_DATA_DIR", str(tmp_path))
    from newton.db import _session_factory

    get_engine.cache_clear()
    _session_factory.cache_clear()
    yield tmp_path
    get_engine.cache_clear()
    _session_factory.cache_clear()


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def seeded_db(isolated_db):
    """isolated_db with migrations applied AND seed data (users/personas).

    Seed matters because tool_approvals.user_id is a FK to users; logging an
    approval for "sir" requires that row to exist.
    """
    from newton.db import get_session, init_db
    from newton.seed import seed_all

    init_db()
    with get_session() as session:
        seed_all(session)
    return isolated_db
