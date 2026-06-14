"""Tests for newton.proactive.recall — vault-driven recall."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import pytest
from click.testing import CliRunner

from newton.cli import cli
from newton.db import get_session, init_db
from newton.models.proactive_notification import ProactiveNotification
from newton.models.user import User
from newton.proactive.alerts import display_text
from newton.proactive.config import RecallConfig
from newton.proactive.recall import RecallEvent, check, extract_recall_note_id
from newton.vault.search import SearchHit

CFG = RecallConfig(
    enabled=True,
    min_score=0.85,
    enabled_modes=["smart", "aggressive"],
    auto_subdir="conversations",
    note_cooldown_minutes=60,
    fetch_limit=5,
)


def _seed_user(user_id: str = "sir") -> None:
    with get_session() as s:
        if s.get(User, user_id) is None:
            s.add(User(user_id=user_id, display_name="Sir"))


def _hit(
    *,
    note_id: int,
    score: float,
    path: str = "_auto/conversations/T1234.md",
) -> SearchHit:
    return SearchHit(
        note_id=note_id,
        chunk_index=0,
        path=path,
        score=score,
        text="snippet",
        owner_user_id="sir",
        status="canonical",
        tags=[],
    )


def _searcher(hits: list[SearchHit]):
    async def fake_search(*_args, **_kwargs):
        return hits

    return fake_search


# ── happy path ────────────────────────────────────────────────────────────


def test_check_fires_when_top_score_crosses_threshold(isolated_db):
    init_db()
    _seed_user()

    async def _run() -> RecallEvent:
        with get_session() as session:
            return await check(
                session,
                "embeddings architecture",
                user_id="sir",
                persona_id="jarvis",
                mode="smart",
                config=CFG,
                searcher=_searcher([_hit(note_id=42, score=0.9)]),
            )

    event = asyncio.run(_run())
    assert event.fired is True
    assert event.note_id == 42
    assert event.score == pytest.approx(0.9)

    with get_session() as s:
        row = s.get(ProactiveNotification, event.notification_id)
    assert row is not None
    assert row.notification_text.startswith("[recall:42] ")
    # display_text must strip the marker.
    rendered = display_text(row.notification_text)
    assert rendered.startswith("Sir,")
    assert "[recall" not in rendered


# ── threshold gating ────────────────────────────────────────────────────


def test_check_does_not_fire_below_min_score(isolated_db):
    init_db()
    _seed_user()

    async def _run() -> RecallEvent:
        with get_session() as session:
            return await check(
                session,
                "trivial topic",
                user_id="sir",
                persona_id="jarvis",
                mode="smart",
                config=CFG,
                searcher=_searcher([_hit(note_id=1, score=0.5)]),
            )

    event = asyncio.run(_run())
    assert event.fired is False
    assert event.reason == "below_min_score"
    assert event.score == pytest.approx(0.5)


# ── mode awareness ──────────────────────────────────────────────────────


def test_check_skipped_in_minimal_mode(isolated_db):
    init_db()
    _seed_user()

    async def _run() -> RecallEvent:
        with get_session() as session:
            return await check(
                session,
                "anything",
                user_id="sir",
                persona_id="jarvis",
                mode="minimal",
                config=CFG,
                searcher=_searcher([_hit(note_id=1, score=0.99)]),
            )

    event = asyncio.run(_run())
    assert event.fired is False
    assert "minimal" in event.reason


def test_check_skipped_in_off_mode(isolated_db):
    init_db()
    _seed_user()

    async def _run() -> RecallEvent:
        with get_session() as session:
            return await check(
                session,
                "anything",
                user_id="sir",
                persona_id="jarvis",
                mode="off",
                config=CFG,
                searcher=_searcher([_hit(note_id=1, score=0.99)]),
            )

    event = asyncio.run(_run())
    assert event.fired is False


def test_check_disabled_via_config(isolated_db):
    init_db()
    _seed_user()
    cfg = RecallConfig(enabled=False)

    async def _run() -> RecallEvent:
        with get_session() as session:
            return await check(
                session,
                "anything",
                user_id="sir",
                persona_id="jarvis",
                mode="smart",
                config=cfg,
                searcher=_searcher([_hit(note_id=1, score=0.99)]),
            )

    event = asyncio.run(_run())
    assert event.fired is False
    assert event.reason == "recall_disabled"


# ── path filter ─────────────────────────────────────────────────────────


def test_check_ignores_non_conversation_paths(isolated_db):
    init_db()
    _seed_user()

    async def _run() -> RecallEvent:
        with get_session() as session:
            return await check(
                session,
                "embeddings",
                user_id="sir",
                persona_id="jarvis",
                mode="smart",
                config=CFG,
                searcher=_searcher(
                    [_hit(note_id=1, score=0.99, path="notes/sir/random.md")]
                ),
            )

    event = asyncio.run(_run())
    assert event.fired is False
    assert event.reason == "no_conversation_hits"


def test_check_matches_path_prefix(isolated_db):
    """Both leading-slash and bare-prefix paths should match."""
    init_db()
    _seed_user()

    async def _run(*, note_id: int, path: str) -> RecallEvent:
        with get_session() as session:
            return await check(
                session,
                "anything",
                user_id="sir",
                persona_id="jarvis",
                mode="smart",
                config=CFG,
                searcher=_searcher([_hit(note_id=note_id, score=0.9, path=path)]),
            )

    e1 = asyncio.run(_run(note_id=10, path="_auto/conversations/T1.md"))
    e2 = asyncio.run(_run(note_id=11, path="/_auto/conversations/T2.md"))
    assert e1.fired is True
    assert e2.fired is True


# ── cooldown ────────────────────────────────────────────────────────────


def test_note_cooldown_suppresses_repeat(isolated_db):
    init_db()
    _seed_user()
    now = datetime(2026, 6, 14, 12, 0, 0)

    async def _fire() -> RecallEvent:
        with get_session() as session:
            return await check(
                session,
                "embeddings architecture",
                user_id="sir",
                persona_id="jarvis",
                mode="smart",
                config=CFG,
                searcher=_searcher([_hit(note_id=42, score=0.9)]),
                now=now,
            )

    first = asyncio.run(_fire())
    assert first.fired is True

    async def _retry() -> RecallEvent:
        with get_session() as session:
            return await check(
                session,
                "embeddings architecture",
                user_id="sir",
                persona_id="jarvis",
                mode="smart",
                config=CFG,
                searcher=_searcher([_hit(note_id=42, score=0.9)]),
                now=now + timedelta(minutes=5),
            )

    second = asyncio.run(_retry())
    assert second.fired is False
    assert second.reason == "note_cooldown"


def test_note_cooldown_per_note_id(isolated_db):
    """Cooldown of note 42 shouldn't suppress a hit on note 99."""
    init_db()
    _seed_user()
    now = datetime(2026, 6, 14, 12, 0, 0)

    async def _hit42() -> RecallEvent:
        with get_session() as session:
            return await check(
                session,
                "x",
                user_id="sir",
                persona_id="jarvis",
                mode="smart",
                config=CFG,
                searcher=_searcher([_hit(note_id=42, score=0.9)]),
                now=now,
            )

    async def _hit99() -> RecallEvent:
        with get_session() as session:
            return await check(
                session,
                "y",
                user_id="sir",
                persona_id="jarvis",
                mode="smart",
                config=CFG,
                searcher=_searcher([_hit(note_id=99, score=0.9)]),
                now=now + timedelta(minutes=5),
            )

    asyncio.run(_hit42())
    second = asyncio.run(_hit99())
    assert second.fired is True


# ── empty message ──────────────────────────────────────────────────────


def test_empty_message_is_skipped(isolated_db):
    init_db()
    _seed_user()

    async def _run() -> RecallEvent:
        with get_session() as session:
            return await check(
                session,
                "   ",
                user_id="sir",
                persona_id="jarvis",
                mode="smart",
                config=CFG,
                searcher=_searcher([_hit(note_id=1, score=0.99)]),
            )

    event = asyncio.run(_run())
    assert event.fired is False
    assert event.reason == "empty_message"


# ── display_text uniformity ─────────────────────────────────────────────


def test_display_text_strips_recall_marker():
    stored = "[recall:42] Sir, last time you decided to use TEI."
    assert display_text(stored) == "Sir, last time you decided to use TEI."


def test_display_text_still_strips_alert_kind():
    """Step 4.2's alert prefix continues to be stripped after the 4.9 widening."""
    stored = "[cpu_high] Sir, CPU at 95%."
    assert display_text(stored) == "Sir, CPU at 95%."


def test_extract_recall_note_id():
    assert extract_recall_note_id("[recall:42] Sir, ...") == 42
    assert extract_recall_note_id("Sir, no marker") is None
    assert extract_recall_note_id("[cpu_high] Sir, ...") is None


# ── CLI ────────────────────────────────────────────────────────────────


def test_cli_recall_check_fires(seeded_db, monkeypatch):
    async def fake_search(*_args, **_kwargs):
        return [_hit(note_id=42, score=0.9)]

    monkeypatch.setattr(
        "newton.proactive.recall._default_searcher", lambda: fake_search
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "proactive",
            "recall-check",
            "embeddings architecture",
            "--user",
            "sir",
            "--persona",
            "jarvis",
            "--mode",
            "smart",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["fired"] is True
    assert payload["note_id"] == 42


def test_cli_recall_check_below_threshold(seeded_db, monkeypatch):
    async def fake_search(*_args, **_kwargs):
        return [_hit(note_id=1, score=0.4)]

    monkeypatch.setattr(
        "newton.proactive.recall._default_searcher", lambda: fake_search
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "proactive",
            "recall-check",
            "x",
            "--mode",
            "smart",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["fired"] is False
    assert payload["reason"] == "below_min_score"
