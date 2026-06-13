"""Tests for newton.memory.briefing (deterministic, no LLM, DB only)."""

from __future__ import annotations


def _add_activity(session, activity_type, status="pending_review"):
    from newton.models import GuestActivity

    row = GuestActivity(
        activity_type=activity_type,
        summary=f"{activity_type} thing",
        status=status,
    )
    session.add(row)
    session.flush()
    return row


def test_generate_briefing_counts_by_type(seeded_db):
    from newton.db import get_session
    from newton.memory.briefing import generate_briefing

    with get_session() as session:
        _add_activity(session, "search")
        _add_activity(session, "search")
        _add_activity(session, "code")
        # rejected one must not be counted
        _add_activity(session, "learning", status="rejected")

        b = generate_briefing(session, "sir")

    assert b.counts.get("search") == 2
    assert b.counts.get("code") == 1
    assert "learning" not in b.counts  # rejected excluded
    assert b.pending_total == 3
    assert not b.is_empty


def test_generate_briefing_empty(seeded_db):
    from newton.db import get_session
    from newton.memory.briefing import generate_briefing

    with get_session() as session:
        b = generate_briefing(session, "sir")
    assert b.is_empty
    assert b.pending_total == 0


def test_render_briefing_lists_counts_and_total():
    from newton.memory.briefing import Briefing, render_briefing

    b = Briefing(
        user_id="sir",
        since=None,
        counts={"search": 2, "code": 1, "learning": 3},
        pending_total=6,
    )
    text = render_briefing(b, display_name="Alex")
    assert "Welcome back, Alex." in text
    assert "2 web searches" in text
    assert "1 code analysis" in text  # singular
    assert "3 learning candidates" in text
    assert "6 items in quarantine." in text


def test_render_briefing_singular_grammar():
    from newton.memory.briefing import Briefing, render_briefing

    b = Briefing(user_id="sir", since=None, counts={"search": 1}, pending_total=1)
    text = render_briefing(b)
    assert "1 web search" in text  # singular, no 's'
    assert "1 item in quarantine." in text


def test_render_briefing_empty():
    from newton.memory.briefing import Briefing, render_briefing

    b = Briefing(user_id="sir", since=None, counts={}, pending_total=0)
    text = render_briefing(b)
    assert "No guest activity" in text


def test_briefing_on_activation_returns_none_when_empty(seeded_db):
    from dataclasses import dataclass

    from newton.db import get_session
    from newton.memory.briefing import briefing_on_activation

    @dataclass
    class FakeActivation:
        user_id: str
        persona_id: str

    with get_session() as session:
        result = briefing_on_activation(session, FakeActivation("sir", "jarvis"))
    assert result is None


def test_briefing_on_activation_speaks_when_pending(seeded_db):
    from dataclasses import dataclass

    from newton.db import get_session
    from newton.memory.briefing import briefing_on_activation

    @dataclass
    class FakeActivation:
        user_id: str
        persona_id: str

    with get_session() as session:
        _add_activity(session, "search")
        result = briefing_on_activation(session, FakeActivation("sir", "jarvis"))
    assert result is not None
    assert "Welcome back" in result
    assert "1 web search" in result
