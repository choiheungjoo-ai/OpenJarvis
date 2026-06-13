"""Tests for sequence pattern detection."""

from __future__ import annotations

from datetime import datetime, timedelta

from newton.db import get_session, init_db
from newton.models.tool_approval import ToolApproval
from newton.models.user import User
from newton.proactive.patterns import sequence


def _seed_user(user_id: str = "sir") -> None:
    with get_session() as s:
        if s.get(User, user_id) is None:
            s.add(User(user_id=user_id, display_name="Sir"))


def _approve(t: datetime, tool: str, user_id: str = "sir") -> ToolApproval:
    return ToolApproval(
        tool_name=tool,
        risk_level=1,
        user_id=user_id,
        decision="approved",
        decided_at=t,
    )


BASE = datetime(2026, 6, 1, 10, 0, 0)
WINDOW_START = BASE - timedelta(days=1)


# ── basic numerator/denominator ────────────────────────────────────────────


def test_perfect_consistency_when_b_always_follows(isolated_db):
    """A → B every time, well within window."""

    init_db()
    _seed_user()

    with get_session() as s:
        for i in range(5):
            t = BASE + timedelta(days=i)
            s.add(_approve(t, "vault_search"))
            s.add(_approve(t + timedelta(minutes=2), "vault_write"))

    with get_session() as s:
        obs = sequence.detect(s, "sir", WINDOW_START, window_seconds=600)

    pair = next(
        o
        for o in obs
        if o.after_tool == "vault_search" and o.then_tool == "vault_write"
    )
    assert pair.occurrences == 5
    assert pair.opportunities == 5


def test_partial_consistency(isolated_db):
    """3 of 5 A-events have B in window."""

    init_db()
    _seed_user()

    with get_session() as s:
        for i in range(5):
            t = BASE + timedelta(days=i)
            s.add(_approve(t, "vault_search"))
            if i < 3:
                s.add(_approve(t + timedelta(minutes=2), "vault_write"))

    with get_session() as s:
        obs = sequence.detect(s, "sir", WINDOW_START, window_seconds=600)

    pair = next(
        o
        for o in obs
        if o.after_tool == "vault_search" and o.then_tool == "vault_write"
    )
    assert pair.occurrences == 3
    assert pair.opportunities == 5


def test_b_outside_window_does_not_count(isolated_db):
    """A → B at 700s is outside a 600s window — not counted."""

    init_db()
    _seed_user()

    with get_session() as s:
        s.add(_approve(BASE, "vault_search"))
        s.add(_approve(BASE + timedelta(seconds=700), "vault_write"))

    with get_session() as s:
        obs = sequence.detect(s, "sir", WINDOW_START, window_seconds=600)

    # No (vault_search, vault_write) observation should exist —
    # the A had no B follow within the window.
    pairs = [(o.after_tool, o.then_tool) for o in obs]
    assert ("vault_search", "vault_write") not in pairs


# ── back-to-back A dedupe ──────────────────────────────────────────────────


def test_back_to_back_a_dedupes_to_one_anchor(isolated_db):
    """Three vault_search in 90 s + one vault_write → opportunities=1, occurrences=1."""

    init_db()
    _seed_user()

    with get_session() as s:
        s.add(_approve(BASE, "vault_search"))
        s.add(_approve(BASE + timedelta(seconds=30), "vault_search"))
        s.add(_approve(BASE + timedelta(seconds=60), "vault_search"))
        s.add(_approve(BASE + timedelta(minutes=2), "vault_write"))

    with get_session() as s:
        obs = sequence.detect(s, "sir", WINDOW_START, window_seconds=600)

    pair = next(
        o
        for o in obs
        if o.after_tool == "vault_search" and o.then_tool == "vault_write"
    )
    assert pair.opportunities == 1, "3 back-to-back A-events should dedupe to 1 anchor"
    assert pair.occurrences == 1


def test_far_apart_a_events_each_count(isolated_db):
    """Two vault_search 11 minutes apart are two separate anchors."""

    init_db()
    _seed_user()

    with get_session() as s:
        s.add(_approve(BASE, "vault_search"))
        s.add(_approve(BASE + timedelta(minutes=11), "vault_search"))
        # Only the second has a follow-up
        s.add(_approve(BASE + timedelta(minutes=12), "vault_write"))

    with get_session() as s:
        obs = sequence.detect(s, "sir", WINDOW_START, window_seconds=600)

    pair = next(
        o
        for o in obs
        if o.after_tool == "vault_search" and o.then_tool == "vault_write"
    )
    assert pair.opportunities == 2
    assert pair.occurrences == 1


# ── decision filter ───────────────────────────────────────────────────────


def test_denied_rows_excluded_from_numerator_and_denominator(isolated_db):
    """Denied attempts are neither A-anchors nor valid B-follows."""

    init_db()
    _seed_user()

    with get_session() as s:
        s.add(_approve(BASE, "vault_search"))
        s.add(_approve(BASE + timedelta(minutes=2), "vault_write"))
        # A denied search — should not appear as an A-anchor
        s.add(
            ToolApproval(
                tool_name="vault_search",
                risk_level=1,
                user_id="sir",
                decision="denied",
                decided_at=BASE + timedelta(hours=2),
            )
        )
        # A denied write following a real search — should not count as B
        s.add(_approve(BASE + timedelta(hours=3), "vault_search"))
        s.add(
            ToolApproval(
                tool_name="vault_write",
                risk_level=2,
                user_id="sir",
                decision="denied",
                decided_at=BASE + timedelta(hours=3, minutes=2),
            )
        )

    with get_session() as s:
        obs = sequence.detect(s, "sir", WINDOW_START, window_seconds=600)

    pair = next(
        o
        for o in obs
        if o.after_tool == "vault_search" and o.then_tool == "vault_write"
    )
    # Only the first search has an approved write following.
    # 2 searches counted as anchors (approved only), 1 has a B follow.
    assert pair.opportunities == 2
    assert pair.occurrences == 1


# ── user isolation ────────────────────────────────────────────────────────


def test_user_isolation(isolated_db):
    init_db()
    _seed_user("sir")
    _seed_user("gf")

    with get_session() as s:
        s.add(_approve(BASE, "vault_search", user_id="gf"))
        s.add(_approve(BASE + timedelta(minutes=2), "vault_write", user_id="gf"))

    with get_session() as s:
        obs_sir = sequence.detect(s, "sir", WINDOW_START, window_seconds=600)
        obs_gf = sequence.detect(s, "gf", WINDOW_START, window_seconds=600)

    assert obs_sir == []
    assert any(
        o.after_tool == "vault_search" and o.then_tool == "vault_write" for o in obs_gf
    )


# ── pair enumeration ──────────────────────────────────────────────────────


def test_unrelated_pairs_not_emitted(isolated_db):
    """If C never follows A within window, no (A, C) row."""

    init_db()
    _seed_user()

    with get_session() as s:
        s.add(_approve(BASE, "vault_search"))
        s.add(_approve(BASE + timedelta(hours=4), "calendar_check"))

    with get_session() as s:
        obs = sequence.detect(s, "sir", WINDOW_START, window_seconds=600)

    pairs = [(o.after_tool, o.then_tool) for o in obs]
    assert ("vault_search", "calendar_check") not in pairs
