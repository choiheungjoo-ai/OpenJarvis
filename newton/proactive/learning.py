"""Reaction learning + nag prevention — block 4 step 4.6.

When sir reacts to a notification, the engine should learn:

    accepted → confirmation; future predictions for this pattern keep
               their full score
    rejected → strong negative; pattern is suppressed for a while
    ignored  → soft negative; pattern is dampened for a shorter while

The doc proposed mutating ``user_patterns.occurrences``. We don't —
the learner rewrites that column each run to the in-window count
(step 4.3's idempotency + decay-aware guarantee), so mutations from
reactions would be overwritten on the next ``patterns learn``.

Instead, the *penalty* is computed at predict time from recent
``proactive_notifications.user_response`` rows. Each ``rejected`` row
within ``rejected_ttl_days`` contributes ``rejected_weight``; each
``ignored`` row within ``ignored_ttl_days`` contributes
``ignored_weight``. The sum is clipped to [0, 1] and folded into the
anticipation score via the ``penalty`` parameter that's already
plumbed through ``score_with_breakdown`` since step 4.3.

Auto-ignore: a notification with no explicit reaction after
``auto_ignore_minutes`` minutes is marked ``ignored``. The scheduler
calls this periodically inside the daemon tick.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from newton.models.proactive_notification import ProactiveNotification
from newton.proactive.config import ReactionLearningConfig, load_proactive_config

REACTIONS = ("accepted", "rejected", "ignored")


@dataclass(frozen=True, slots=True)
class ReactionResult:
    """Outcome of recording one reaction."""

    notification_id: int
    user_id: str
    pattern_id: int | None
    reaction: str
    response_at: datetime


def record_reaction(
    db_session: Session,
    notification_id: int,
    reaction: str,
    now: datetime | None = None,
) -> ReactionResult:
    """Mark a notification with sir's response. Idempotent on re-call.

    Raises ``ValueError`` if the notification doesn't exist or the
    reaction is not one of accepted/rejected/ignored. Replacing an
    earlier reaction with a different one is allowed — the most
    recent ``response_at`` wins.
    """
    if reaction not in REACTIONS:
        raise ValueError(f"reaction must be one of {REACTIONS}, got {reaction!r}")
    if now is None:
        now = datetime.now()

    row = db_session.get(ProactiveNotification, notification_id)
    if row is None:
        raise ValueError(f"no notification with id={notification_id}")

    row.user_response = reaction
    row.response_at = now
    db_session.flush()

    return ReactionResult(
        notification_id=row.notification_id,
        user_id=row.user_id,
        pattern_id=row.trigger_pattern_id,
        reaction=reaction,
        response_at=now,
    )


def compute_pattern_penalty(
    db_session: Session,
    user_id: str,
    pattern_id: int,
    config: ReactionLearningConfig,
    now: datetime | None = None,
) -> float:
    """Sum the contributions of recent reactions to a pattern's penalty.

    Returns a value in [0, 1] suitable to pass to
    :func:`newton.proactive.patterns.confidence.score_with_breakdown`'s
    ``penalty`` parameter or to fold directly into the anticipation
    engine's ``confidence × (1 - penalty)`` reduction.
    """
    if now is None:
        now = datetime.now()

    rejected_cutoff = now - timedelta(days=config.rejected_ttl_days)
    ignored_cutoff = now - timedelta(days=config.ignored_ttl_days)

    n_rejected = (
        db_session.execute(
            select(ProactiveNotification.notification_id).where(
                ProactiveNotification.user_id == user_id,
                ProactiveNotification.trigger_pattern_id == pattern_id,
                ProactiveNotification.user_response == "rejected",
                ProactiveNotification.response_at >= rejected_cutoff,
            )
        )
        .scalars()
        .all()
    )
    n_ignored = (
        db_session.execute(
            select(ProactiveNotification.notification_id).where(
                ProactiveNotification.user_id == user_id,
                ProactiveNotification.trigger_pattern_id == pattern_id,
                ProactiveNotification.user_response == "ignored",
                ProactiveNotification.response_at >= ignored_cutoff,
            )
        )
        .scalars()
        .all()
    )

    total = (
        len(n_rejected) * config.rejected_weight
        + len(n_ignored) * config.ignored_weight
    )
    return max(0.0, min(1.0, total))


def mark_stale_as_ignored(
    db_session: Session,
    config: ReactionLearningConfig | None = None,
    now: datetime | None = None,
) -> int:
    """Auto-flag rows older than ``auto_ignore_minutes`` with no response.

    Returns the number of rows updated.  Safe to call frequently — only
    rows with NULL ``user_response`` and a ``sent_at`` older than the
    threshold are touched.
    """
    if config is None:
        config = load_proactive_config().reactions
    if now is None:
        now = datetime.now()

    cutoff = now - timedelta(minutes=config.auto_ignore_minutes)
    stmt = (
        update(ProactiveNotification)
        .where(
            ProactiveNotification.user_response.is_(None),
            ProactiveNotification.sent_at < cutoff,
        )
        .values(user_response="ignored", response_at=now)
    )
    result = db_session.execute(stmt)
    return result.rowcount or 0


__all__ = [
    "REACTIONS",
    "ReactionResult",
    "compute_pattern_penalty",
    "mark_stale_as_ignored",
    "record_reaction",
]
