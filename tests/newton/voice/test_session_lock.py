"""Tests for newton.voice.session_lock — multi-speaker policy."""

from __future__ import annotations

from datetime import datetime, timedelta

from newton.voice.config import SessionLockConfig
from newton.voice.session_lock import LockState, SessionLock

CFG = SessionLockConfig(timeout_seconds=30)
T0 = datetime(2026, 6, 14, 12, 0, 0)


def _lock() -> SessionLock:
    return SessionLock(config=CFG)


# ── empty lock passes everyone ──────────────────────────────────────────


def test_unlocked_session_passes_any_speaker():
    lock = _lock()
    assert lock.apply_audio("sir", T0) is True
    assert lock.apply_audio("gf", T0) is True
    assert lock.apply_audio(None, T0) is True
    assert lock.is_locked is False


# ── lock_to ─────────────────────────────────────────────────────────────


def test_lock_to_records_user_and_timestamp():
    lock = _lock()
    lock.lock_to("sir", T0)
    assert lock.is_locked is True
    state = lock.state()
    assert state.locked_user_id == "sir"
    assert state.locked_at == T0
    assert state.last_activity_at == T0


def test_lock_to_is_first_call_wins():
    lock = _lock()
    lock.lock_to("sir", T0)
    lock.lock_to("gf", T0 + timedelta(milliseconds=100))
    assert lock.state().locked_user_id == "sir"


# ── locked-user audio passes ───────────────────────────────────────────


def test_locked_user_audio_passes_and_extends_lock():
    lock = _lock()
    lock.lock_to("sir", T0)
    now = T0 + timedelta(seconds=10)
    assert lock.apply_audio("sir", now) is True
    assert lock.state().last_activity_at == now


# ── non-locked user audio is dropped ──────────────────────────────────


def test_non_locked_user_audio_is_dropped():
    lock = _lock()
    lock.lock_to("sir", T0)
    assert lock.apply_audio("gf", T0 + timedelta(seconds=5)) is False
    # Drop must NOT extend the lock's last_activity_at.
    assert lock.state().last_activity_at == T0


def test_unknown_speaker_dropped_when_locked():
    lock = _lock()
    lock.lock_to("sir", T0)
    assert lock.apply_audio(None, T0 + timedelta(seconds=5)) is False


# ── timeout / heal ─────────────────────────────────────────────────────


def test_timeout_heals_on_apply_audio():
    """30 s past last activity → the lock releases and the chunk passes."""
    lock = _lock()
    lock.lock_to("sir", T0)
    # 35 s of silence; lock should heal and gf can pass.
    now = T0 + timedelta(seconds=35)
    assert lock.apply_audio("gf", now) is True
    # Heal cleared the lock entirely.
    assert lock.is_locked is False


def test_timeout_inclusive_at_boundary():
    """Exactly timeout_seconds is treated as expired (>=)."""
    lock = _lock()
    lock.lock_to("sir", T0)
    now = T0 + timedelta(seconds=30)
    assert lock.apply_audio("gf", now) is True
    assert lock.is_locked is False


def test_just_inside_timeout_still_locked():
    lock = _lock()
    lock.lock_to("sir", T0)
    now = T0 + timedelta(seconds=29, milliseconds=999)
    assert lock.apply_audio("gf", now) is False
    assert lock.is_locked is True


def test_continuous_sir_activity_extends_lock_past_default_timeout():
    """Within the timeout, sir's activity keeps the lock alive forever."""
    lock = _lock()
    lock.lock_to("sir", T0)
    # Speak every 20 s for 5 minutes — lock never expires.
    for i in range(15):
        when = T0 + timedelta(seconds=20 * (i + 1))
        assert lock.apply_audio("sir", when) is True
    assert lock.is_locked is True


# ── clear ──────────────────────────────────────────────────────────────


def test_clear_releases_lock():
    lock = _lock()
    lock.lock_to("sir", T0)
    lock.clear()
    assert lock.is_locked is False
    # And after clear, anyone can pass.
    assert lock.apply_audio("gf", T0 + timedelta(seconds=1)) is True


# ── can_approve ───────────────────────────────────────────────────────


def test_can_approve_requires_locked_user_match():
    lock = _lock()
    lock.lock_to("sir", T0)
    assert lock.can_approve("sir", T0 + timedelta(seconds=5)) is True
    assert lock.can_approve("gf", T0 + timedelta(seconds=5)) is False


def test_can_approve_returns_false_when_unlocked():
    lock = _lock()
    assert lock.can_approve("sir", T0) is False


def test_can_approve_returns_false_for_unknown_user():
    lock = _lock()
    lock.lock_to("sir", T0)
    assert lock.can_approve(None, T0 + timedelta(seconds=5)) is False


def test_can_approve_heals_expired_lock():
    lock = _lock()
    lock.lock_to("sir", T0)
    assert lock.can_approve("sir", T0 + timedelta(seconds=35)) is False
    assert lock.is_locked is False


# ── LockState ─────────────────────────────────────────────────────────


def test_lockstate_is_locked_property():
    s = LockState(
        locked_user_id="sir",
        locked_at=T0,
        last_activity_at=T0,
        timeout_seconds=30,
    )
    assert s.is_locked is True

    empty = LockState(
        locked_user_id=None, locked_at=None, last_activity_at=None, timeout_seconds=30
    )
    assert empty.is_locked is False


def test_state_with_now_heals():
    lock = _lock()
    lock.lock_to("sir", T0)
    state = lock.state(now=T0 + timedelta(seconds=35))
    assert state.locked_user_id is None
