"""Vault-driven proactive recall — block 4 step 4.9.

When sir's new message touches a topic that an old conversation
summary covers, Newton surfaces the past one. The block-3 vault +
session summarizer (``_auto/conversations/``) is the memory; this
module is the eyes.

Flow per incoming message::

    if config.recall.enabled and mode in config.recall.enabled_modes:
        hits = search(message_text, user_id, persona_id, limit=fetch_limit)
        hits = [h for h in hits if "_auto/<auto_subdir>/" in h.path]
        top = max(hits, key=score) if hits else None
        if top and top.score >= min_score and not in_note_cooldown(top):
            insert proactive_notifications row → block 4.7 delivers

The vault searcher is injected (default = ``newton.vault.search.search``)
so this module can be unit-tested without Qdrant + TEI.

Cooldown is keyed off the matched ``note_id``, not the pattern (these
recall rows have no ``trigger_pattern_id``). Stored as a marker in
``notification_text`` similar to the alert ``[kind]`` prefix —
``[recall:<note_id>] Sir, last time...``. ``display_text`` strips it
so sir never sees the marker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from newton.models.proactive_notification import ProactiveNotification
from newton.proactive.config import RecallConfig, load_proactive_config
from newton.vault.search import SearchHit

#: Storage marker for recall rows. ``alerts.display_text`` strips both
#: this and the alert ``[kind]`` marker so user-facing surfaces never
#: see either.
_RECALL_MARKER_RE = re.compile(r"^\[recall:(\d+)\]\s")


SearchFn = Callable[..., Awaitable[list[SearchHit]]]


@dataclass(frozen=True, slots=True)
class RecallEvent:
    """Outcome of one ``recall.check`` call."""

    fired: bool
    reason: str
    notification_id: int | None = None
    note_id: int | None = None
    score: float | None = None


def extract_recall_note_id(stored: str) -> int | None:
    """Return the matched ``note_id`` from a recall row, or None."""
    match = _RECALL_MARKER_RE.match(stored)
    return int(match.group(1)) if match else None


def _default_searcher() -> SearchFn:
    from newton.vault.search import search

    return search


def _is_conversation_path(path: str, auto_subdir: str) -> bool:
    """Match _auto/<auto_subdir>/... — both leading slash and bare prefixes."""
    needle = f"/_auto/{auto_subdir}/"
    return needle in f"/{path.strip('/')}/" or path.startswith(f"_auto/{auto_subdir}/")


def _note_in_cooldown(
    db_session: Session,
    user_id: str,
    note_id: int,
    config: RecallConfig,
    now: datetime,
) -> bool:
    cutoff = now - timedelta(minutes=config.note_cooldown_minutes)
    hit = db_session.execute(
        select(ProactiveNotification.notification_id)
        .where(
            ProactiveNotification.user_id == user_id,
            ProactiveNotification.notification_text.like(f"[recall:{note_id}] %"),
            ProactiveNotification.sent_at > cutoff,
        )
        .limit(1)
    ).first()
    return hit is not None


async def check(
    db_session: Session,
    message: str,
    user_id: str,
    persona_id: str,
    *,
    mode: str = "smart",
    config: RecallConfig | None = None,
    searcher: SearchFn | None = None,
    now: datetime | None = None,
) -> RecallEvent:
    """Fire a recall row if the message matches an old conversation summary.

    Returns a :class:`RecallEvent` describing what happened — useful
    for tests and for the daemon's reporting.
    """
    if config is None:
        config = load_proactive_config().recall
    if now is None:
        now = datetime.now()

    if not config.enabled:
        return RecallEvent(fired=False, reason="recall_disabled")
    if mode not in set(config.enabled_modes):
        return RecallEvent(fired=False, reason=f"mode={mode}_disallowed")
    if not message.strip():
        return RecallEvent(fired=False, reason="empty_message")

    if searcher is None:
        searcher = _default_searcher()

    hits = await searcher(
        message,
        user_id,
        persona_id,
        limit=config.fetch_limit,
    )
    # Filter to conversation summaries only.
    eligible = [h for h in hits if _is_conversation_path(h.path, config.auto_subdir)]
    if not eligible:
        return RecallEvent(fired=False, reason="no_conversation_hits")

    top = max(eligible, key=lambda h: h.score)
    if top.score < config.min_score:
        return RecallEvent(
            fired=False, reason="below_min_score", note_id=top.note_id, score=top.score
        )

    if _note_in_cooldown(db_session, user_id, top.note_id, config, now):
        return RecallEvent(
            fired=False,
            reason="note_cooldown",
            note_id=top.note_id,
            score=top.score,
        )

    stored = (
        f"[recall:{top.note_id}] Sir, last time you discussed this it was in "
        f"{top.path}. Want to surface that conversation?"
    )
    row = ProactiveNotification(
        user_id=user_id,
        trigger_pattern_id=None,  # recall has no pattern id
        notification_text=stored,
        sent_at=now,
    )
    db_session.add(row)
    db_session.flush()
    return RecallEvent(
        fired=True,
        reason="fired",
        notification_id=row.notification_id,
        note_id=top.note_id,
        score=top.score,
    )


__all__ = [
    "RecallEvent",
    "check",
    "extract_recall_note_id",
]
