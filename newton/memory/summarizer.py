"""Session summarization.

When a ChatSession ends, its messages are condensed into a short markdown
note (topics, decisions, action items, sentiment) and written into the
vault under ``<auto_dir>/conversations/`` so it becomes searchable via RAG.

The actual language-model call is abstracted behind ``SessionSummarizer``
so this module stays testable and model-agnostic: block 3 owns *building
and storing* the note; *which* LLM produces the prose is a later-block
concern, injected here. ``FakeSummarizer`` gives deterministic output for
tests and offline use.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import frontmatter

# Placeholder shown when a section has no items.
_EMPTY = "_(none)_"


@dataclass
class SessionTranscript:
    """The raw material a summarizer works from."""

    session_id: str
    user_id: str
    persona_id: str
    started_at: datetime | None
    ended_at: datetime | None
    # (role, content) pairs in chronological order.
    turns: list[tuple[str, str]] = field(default_factory=list)

    @property
    def duration_min(self) -> int | None:
        if self.started_at and self.ended_at:
            secs = (self.ended_at - self.started_at).total_seconds()
            return max(0, int(secs // 60))
        return None


@dataclass
class SummaryParts:
    """Structured summary a ``SessionSummarizer`` returns."""

    title: str
    topics: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    sentiment: str = ""


class SessionSummarizer(abc.ABC):
    """Turns a transcript into structured summary parts."""

    @abc.abstractmethod
    async def summarize(self, transcript: SessionTranscript) -> SummaryParts: ...


class FakeSummarizer(SessionSummarizer):
    """Deterministic, dependency-free summarizer for tests / offline use.

    Does no NLP: derives a title from the timestamp and lists the user
    turns as "topics". Enough to exercise the note-building and storage
    path without a live model.
    """

    async def summarize(self, transcript: SessionTranscript) -> SummaryParts:
        when = transcript.started_at or transcript.ended_at
        stamp = when.strftime("%Y-%m-%d %H:%M") if when else transcript.session_id
        user_turns = [c.strip() for r, c in transcript.turns if r == "user" and c]
        return SummaryParts(
            title=f"Conversation {stamp}",
            topics=[t[:80] for t in user_turns[:5]],
            decisions=[],
            action_items=[],
            sentiment="(not analyzed)",
        )


def _section(title: str, items: list[str]) -> str:
    if not items:
        return f"## {title}\n{_EMPTY}\n"
    body = "\n".join(f"- {i}" for i in items)
    return f"## {title}\n{body}\n"


def render_summary_markdown(parts: SummaryParts) -> str:
    """Render the body (without frontmatter) from summary parts."""
    return (
        f"# {parts.title}\n\n"
        + _section("Topics", parts.topics)
        + "\n"
        + _section("Key decisions", parts.decisions)
        + "\n"
        + _section("Action items", parts.action_items)
        + "\n## Sentiment\n"
        + (parts.sentiment or _EMPTY)
        + "\n"
    )


def build_summary_note(
    transcript: SessionTranscript, parts: SummaryParts
) -> tuple[str, dict[str, Any]]:
    """Return (markdown_with_frontmatter, frontmatter_dict).

    ACL is private by default: owner + read_users = [owner], and
    read_personas = [the persona the conversation was with].
    """
    when = transcript.started_at or transcript.ended_at or datetime.now(timezone.utc)
    fm: dict[str, Any] = {
        "acl": {
            "owner": transcript.user_id,
            "read_users": [transcript.user_id],
            "read_personas": [transcript.persona_id],
            "status": "canonical",
        },
        "tags": ["conversation", "auto", when.strftime("%Y-%m-%d")],
        "session_id": transcript.session_id,
        "persona": transcript.persona_id,
    }
    if transcript.duration_min is not None:
        fm["duration_min"] = transcript.duration_min

    body = render_summary_markdown(parts)
    post = frontmatter.Post(body, **fm)
    return frontmatter.dumps(post), fm


def summary_note_path(
    vault_root: Path, transcript: SessionTranscript, auto_dir: str = "_auto"
) -> Path:
    """``<auto_dir>/conversations/<YYYY-MM-DD>-<session_id>.md`` under vault."""
    when = transcript.started_at or transcript.ended_at or datetime.now(timezone.utc)
    fname = f"{when.strftime('%Y-%m-%d')}-{transcript.session_id}.md"
    return vault_root / auto_dir / "conversations" / fname


def load_transcript(session: Any, session_id: str) -> SessionTranscript | None:
    """Build a transcript from a ChatSession + its messages."""
    from newton.models import ChatSession

    cs = session.get(ChatSession, session_id)
    if cs is None:
        return None
    turns = [(m.role, m.content or "") for m in cs.messages]
    return SessionTranscript(
        session_id=cs.session_id,
        user_id=cs.user_id,
        persona_id=cs.persona_id,
        started_at=cs.started_at,
        ended_at=cs.ended_at,
        turns=turns,
    )


async def summarize_session(
    session: Any,
    session_id: str,
    summarizer: SessionSummarizer,
    vault_root: Path,
    *,
    auto_dir: str = "_auto",
    mark: bool = True,
) -> Path | None:
    """Summarize one session and write the note. Returns the note path.

    ``mark=True`` stamps ``sessions.summarized_at`` so the trigger layer
    can avoid duplicate work. Returns None if the session does not exist.
    """
    from newton.models import ChatSession

    transcript = load_transcript(session, session_id)
    if transcript is None:
        return None

    parts = await summarizer.summarize(transcript)
    rendered, _fm = build_summary_note(transcript, parts)

    path = summary_note_path(vault_root, transcript, auto_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")

    if mark:
        cs = session.get(ChatSession, session_id)
        if cs is not None:
            cs.summarized_at = datetime.now(timezone.utc)
            session.flush()

    return path


__all__ = [
    "FakeSummarizer",
    "SessionSummarizer",
    "SessionTranscript",
    "SummaryParts",
    "build_summary_note",
    "load_transcript",
    "render_summary_markdown",
    "summarize_session",
    "summary_note_path",
]
