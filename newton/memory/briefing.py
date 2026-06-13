"""JARVIS briefing on guest activity.

When sir returns (a Stage-2 activation routes to a persona he owns), JARVIS
summarizes what guests did in his absence: counts per activity type plus
how many items await review. The summary is a deterministic aggregation —
counting, not prose generation — so it is fast, testable, and needs no
language model. (A future block can swap in an LLM narrator behind the same
``render_briefing`` seam if richer phrasing is wanted.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Human-readable labels for the activity_type enum.
_TYPE_LABELS = {
    "search": "web search",
    "code": "code analysis",
    "chat": "conversation",
    "learning": "learning candidate",
}


@dataclass
class Briefing:
    user_id: str
    since: datetime | None
    counts: dict[str, int] = field(default_factory=dict)
    pending_total: int = 0

    @property
    def is_empty(self) -> bool:
        return self.pending_total == 0


def _plural(label: str, n: int) -> str:
    if n == 1:
        return label
    if label.endswith(("s", "x", "z", "ch", "sh")):
        return label + "es"
    return label + "s"


def generate_briefing(
    session: Any,
    user_id: str,
    *,
    since: datetime | None = None,
) -> Briefing:
    """Aggregate pending guest activity into a Briefing.

    Counts ``pending_review`` GuestActivity rows by type. ``since`` filters
    to activity created at or after that time when given.
    """
    from sqlalchemy import func, select

    from newton.models import GuestActivity

    stmt = (
        select(GuestActivity.activity_type, func.count())
        .where(GuestActivity.status == "pending_review")
        .group_by(GuestActivity.activity_type)
    )
    if since is not None:
        stmt = stmt.where(GuestActivity.created_at >= since)

    counts: dict[str, int] = {}
    for activity_type, n in session.execute(stmt).all():
        counts[activity_type or "learning"] = int(n)

    return Briefing(
        user_id=user_id,
        since=since,
        counts=counts,
        pending_total=sum(counts.values()),
    )


def render_briefing(briefing: Briefing, *, display_name: str = "sir") -> str:
    """Render the briefing as JARVIS would speak it at next activation."""
    if briefing.is_empty:
        return f"Welcome back, {display_name}. No guest activity to report."

    lines = [
        f"Welcome back, {display_name}. Briefing on guest activity in your absence:"
    ]
    # Stable, readable order: known types first, then any extras.
    order = ["search", "code", "chat", "learning"]
    seen = set()
    for key in order:
        if key in briefing.counts:
            n = briefing.counts[key]
            label = _plural(_TYPE_LABELS.get(key, key), n)
            lines.append(f" - {n} {label}")
            seen.add(key)
    for key, n in briefing.counts.items():
        if key in seen:
            continue
        label = _plural(_TYPE_LABELS.get(key, key), n)
        lines.append(f" - {n} {label}")

    lines.append(
        f" - {briefing.pending_total} item"
        f"{'' if briefing.pending_total == 1 else 's'} in quarantine."
    )
    lines.append("How would you like to proceed?")
    return "\n".join(lines)


def briefing_on_activation(
    session: Any, activation: Any, *, display_name: str = "sir"
) -> str | None:
    """If an owner just activated and has pending guest activity, brief them.

    Returns the spoken text, or None when there is nothing to report. The
    caller (the runtime, block 5) decides how/whether to voice it.
    """
    briefing = generate_briefing(session, activation.user_id)
    if briefing.is_empty:
        return None
    return render_briefing(briefing, display_name=display_name)


__all__ = [
    "Briefing",
    "briefing_on_activation",
    "generate_briefing",
    "render_briefing",
]
