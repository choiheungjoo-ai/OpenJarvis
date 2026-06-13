"""Tests for newton.memory.summarizer and triggers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import frontmatter
import pytest

from newton.memory.summarizer import (
    FakeSummarizer,
    SessionTranscript,
    SummaryParts,
    build_summary_note,
    render_summary_markdown,
    summarize_session,
    summary_note_path,
)
from newton.memory.triggers import find_due_sessions, run_due_summarizations


def _transcript(**kw):
    base = dict(
        session_id="T1",
        user_id="sir",
        persona_id="jarvis",
        started_at=datetime(2026, 5, 29, 14, 30, tzinfo=timezone.utc),
        ended_at=datetime(2026, 5, 29, 14, 42, tzinfo=timezone.utc),
        turns=[("user", "Let's design block 3"), ("assistant", "On it.")],
    )
    base.update(kw)
    return SessionTranscript(**base)


# -- pure note building --------------------------------------------------------


def test_duration_min_computed():
    assert _transcript().duration_min == 12


def test_render_includes_all_sections():
    parts = SummaryParts(
        title="Conversation",
        topics=["a", "b"],
        decisions=["use Qdrant"],
        action_items=[],
        sentiment="Focused.",
    )
    md = render_summary_markdown(parts)
    assert "## Topics" in md
    assert "## Key decisions" in md
    assert "## Action items" in md
    assert "## Sentiment" in md
    assert "use Qdrant" in md
    assert "Focused." in md


def test_build_note_acl_is_private():
    parts = SummaryParts(title="C", topics=["x"])
    rendered, fm = build_summary_note(_transcript(), parts)
    assert fm["acl"]["owner"] == "sir"
    assert fm["acl"]["read_users"] == ["sir"]
    assert fm["acl"]["read_personas"] == ["jarvis"]
    assert fm["acl"]["status"] == "canonical"
    # round-trips as valid frontmatter
    post = frontmatter.loads(rendered)
    assert post["session_id"] == "T1"
    assert post["duration_min"] == 12


def test_summary_note_path_uses_auto_dir(tmp_path):
    p = summary_note_path(tmp_path, _transcript(), auto_dir="_auto")
    assert p == tmp_path / "_auto" / "conversations" / "2026-05-29-T1.md"


@pytest.mark.asyncio
async def test_fake_summarizer_lists_user_turns():
    parts = await FakeSummarizer().summarize(_transcript())
    assert parts.title.startswith("Conversation 2026-05-29")
    assert "Let's design block 3" in parts.topics


# -- summarize_session against the DB ------------------------------------------


def _seed_session(session, sid="T1", ended=True):
    from newton.models import ChatSession, Message

    started = datetime(2026, 5, 29, 14, 30, tzinfo=timezone.utc)
    cs = ChatSession(
        session_id=sid,
        user_id="sir",
        persona_id="jarvis",
        started_at=started,
        ended_at=(started + timedelta(minutes=12)) if ended else None,
    )
    session.add(cs)
    session.add(Message(session_id=sid, role="user", content="Design block 3"))
    session.add(Message(session_id=sid, role="assistant", content="Sure."))
    session.flush()


@pytest.mark.asyncio
async def test_summarize_session_writes_note_and_marks(seeded_db, tmp_path):
    from newton.db import get_session
    from newton.models import ChatSession

    with get_session() as session:
        _seed_session(session)
        path = await summarize_session(session, "T1", FakeSummarizer(), tmp_path)
        assert path is not None
        assert path.exists()
        assert path.name == "2026-05-29-T1.md"

        cs = session.get(ChatSession, "T1")
        assert cs.summarized_at is not None

    text = path.read_text()
    assert "Design block 3" in text


@pytest.mark.asyncio
async def test_summarize_unknown_session_returns_none(seeded_db, tmp_path):
    from newton.db import get_session

    with get_session() as session:
        result = await summarize_session(session, "nope", FakeSummarizer(), tmp_path)
    assert result is None


# -- triggers ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_due_includes_ended_excludes_summarized(seeded_db, tmp_path):
    from newton.db import get_session

    with get_session() as session:
        _seed_session(session, sid="ended", ended=True)
        _seed_session(session, sid="open", ended=False)

        due = find_due_sessions(session)
        assert "ended" in due
        assert "open" not in due  # open + recent messages → not idle

        # After summarizing, it drops out of the due list.
        await summarize_session(session, "ended", FakeSummarizer(), tmp_path)
        due_after = find_due_sessions(session)
        assert "ended" not in due_after


@pytest.mark.asyncio
async def test_idle_session_becomes_due(seeded_db, tmp_path):
    from newton.db import get_session
    from newton.models import ChatSession, Message

    with get_session() as session:
        old = datetime(2026, 5, 29, 10, 0, tzinfo=timezone.utc)
        cs = ChatSession(
            session_id="idle",
            user_id="sir",
            persona_id="jarvis",
            started_at=old,
            ended_at=None,
        )
        session.add(cs)
        session.add(
            Message(
                session_id="idle",
                role="user",
                content="hello",
                created_at=old,
            )
        )
        session.flush()

        now = old + timedelta(hours=2)
        due = find_due_sessions(session, now=now, idle_minutes=30)
        assert "idle" in due


@pytest.mark.asyncio
async def test_run_due_summarizations_writes_all(seeded_db, tmp_path):
    from newton.db import get_session

    with get_session() as session:
        _seed_session(session, sid="A", ended=True)
        _seed_session(session, sid="B", ended=True)
        paths = await run_due_summarizations(session, FakeSummarizer(), tmp_path)
    assert len(paths) == 2
    assert all(p.exists() for p in paths)
