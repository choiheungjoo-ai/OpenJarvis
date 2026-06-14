"""Proactive mode resolution + time-bounded reverts (block 4 step 4.8).

Two responsibilities live here:

    1. **Resolve** the effective mode for a user *right now*. Reads
       ``users.proactive_mode`` and ``users.proactive_mode_revert_at``;
       if the revert_at has passed, the mode is treated as the default
       (and the column is healed back on the next ``apply_revert_due``
       call).

    2. **Apply** changes. ``set_mode`` writes the chosen mode and an
       optional revert_at; ``apply_revert_due`` reverts any user whose
       revert_at has elapsed, called by the scheduler each tick.

The scheduler calls ``resolve_mode`` before deciding what to do; step
4.5's existing ``tick(mode=...)`` parameter is the integration seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from newton.models.user import User

VALID_MODES = ("off", "minimal", "smart", "aggressive")


@dataclass(frozen=True, slots=True)
class ResolvedMode:
    """The effective mode plus any revert info the caller may want to log."""

    user_id: str
    mode: str
    revert_at: datetime | None
    reverted_now: bool  # True when this call healed an expired revert


def resolve_mode(
    db_session: Session,
    user_id: str,
    default: str = "smart",
    now: datetime | None = None,
) -> ResolvedMode:
    """Return the current effective mode for ``user_id``.

    If the user's ``proactive_mode_revert_at`` is in the past, this
    *also* heals the columns back to the default — same call, single
    transaction. So callers don't need a separate "tick" path; one
    resolve does it.
    """
    if now is None:
        now = datetime.now()

    user = db_session.get(User, user_id)
    if user is None:
        # No row → conservative default. Don't raise; the scheduler may
        # legitimately resolve a user before the seed step has run.
        return ResolvedMode(
            user_id=user_id, mode=default, revert_at=None, reverted_now=False
        )

    current = user.proactive_mode or default
    revert = user.proactive_mode_revert_at

    if revert is not None and now >= revert:
        user.proactive_mode = default
        user.proactive_mode_revert_at = None
        db_session.flush()
        return ResolvedMode(
            user_id=user_id,
            mode=default,
            revert_at=None,
            reverted_now=True,
        )

    return ResolvedMode(
        user_id=user_id,
        mode=current,
        revert_at=revert,
        reverted_now=False,
    )


def set_mode(
    db_session: Session,
    user_id: str,
    mode: str,
    for_seconds: float | None = None,
    now: datetime | None = None,
) -> ResolvedMode:
    """Set ``user_id``'s mode; pass ``for_seconds`` for a time-bounded change.

    ``for_seconds`` is the wall-clock duration the new mode stays in
    effect; afterward the next ``resolve_mode`` heals the column back
    to the default. ``None`` means permanent — the user's revert_at is
    cleared.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {VALID_MODES}, got {mode!r}")
    if now is None:
        now = datetime.now()

    user = db_session.get(User, user_id)
    if user is None:
        raise ValueError(f"unknown user {user_id!r}")

    revert_at = (
        now + timedelta(seconds=for_seconds) if for_seconds is not None else None
    )
    user.proactive_mode = mode
    user.proactive_mode_revert_at = revert_at
    db_session.flush()
    return ResolvedMode(
        user_id=user_id, mode=mode, revert_at=revert_at, reverted_now=False
    )


def apply_revert_due(
    db_session: Session,
    default: str = "smart",
    now: datetime | None = None,
) -> int:
    """Heal *every* user whose revert_at has elapsed. Returns the count."""
    if now is None:
        now = datetime.now()
    stmt = (
        update(User)
        .where(
            User.proactive_mode_revert_at.is_not(None),
            User.proactive_mode_revert_at <= now,
        )
        .values(proactive_mode=default, proactive_mode_revert_at=None)
    )
    result = db_session.execute(stmt)
    return result.rowcount or 0


def list_modes(db_session: Session) -> list[ResolvedMode]:
    """Snapshot every user's stored mode (no resolve — purely reading)."""
    rows = list(db_session.execute(select(User)).scalars().all())
    out: list[ResolvedMode] = []
    for u in rows:
        out.append(
            ResolvedMode(
                user_id=u.user_id,
                mode=u.proactive_mode or "smart",
                revert_at=u.proactive_mode_revert_at,
                reverted_now=False,
            )
        )
    return out


__all__ = [
    "VALID_MODES",
    "ResolvedMode",
    "apply_revert_due",
    "list_modes",
    "resolve_mode",
    "set_mode",
]
