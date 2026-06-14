"""Multi-speaker session lock (block 5 step 5.10).

After Stage 1 wakes the system and the first speaker is identified,
the session **locks** to that user. Subsequent audio is gated by the
lock — non-locked speakers are dropped silently. The lock releases
after ``timeout_seconds`` of no activity from the locked user, at
which point the next Stage 1 starts fresh.

Edge cases the lock handles:

    * sir talks, gf interrupts → gf's audio drops.
    * sir leaves the room, gf takes over → must Stage 1 again.
    * sir and gf both wake at the same time → earliest timestamp wins.
    * the voice approval channel (step 5.13) honours the lock: only
      the locked user can approve.

The lock is intentionally simple state with explicit time: every
method takes ``now`` so tests can inject deterministic timestamps and
production code passes ``datetime.now()``. No global state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from newton.voice.config import SessionLockConfig

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LockState:
    """Snapshot of the lock at a moment, for telemetry / tests."""

    locked_user_id: str | None
    locked_at: datetime | None
    last_activity_at: datetime | None
    timeout_seconds: int

    @property
    def is_locked(self) -> bool:
        return self.locked_user_id is not None


@dataclass
class SessionLock:
    """Stateful lock — one per voice session loop.

    Construct fresh after each Stage-1 wake; the lock is *not* meant
    to outlive the conversation. ``apply_audio`` is the main entry
    point: it tells the caller whether to pass or drop the chunk.
    """

    config: SessionLockConfig
    _locked_user_id: str | None = None
    _locked_at: datetime | None = None
    _last_activity_at: datetime | None = None

    # ── lifecycle ──────────────────────────────────────────────────

    def lock_to(self, user_id: str, now: datetime) -> None:
        """Lock the session to ``user_id``. First-call-wins (earlier timestamp)."""
        if self._locked_user_id is not None:
            # Already locked — ignore later attempts. The "earliest
            # timestamp wins" rule is handled by the caller passing
            # the right ``now``; we don't reach back in time.
            log.debug(
                "session already locked to %r; ignoring lock_to(%r)",
                self._locked_user_id,
                user_id,
            )
            return
        self._locked_user_id = user_id
        self._locked_at = now
        self._last_activity_at = now

    def clear(self) -> None:
        """Wipe the lock so the next Stage 1 starts fresh."""
        self._locked_user_id = None
        self._locked_at = None
        self._last_activity_at = None

    # ── gating ────────────────────────────────────────────────────

    def apply_audio(self, user_id: str | None, now: datetime) -> bool:
        """Return True if a chunk from ``user_id`` should pass.

        ``user_id=None`` means "speaker unknown" (Voice ID couldn't
        decide). Unknown speakers don't extend the lock and are
        dropped if the session is currently locked to someone.

        If the lock has expired, the lock is cleared first; the caller
        gets a clean slate. Stage 1 then needs to re-lock on the next
        wake-word / clap.
        """
        # Heal an expired lock before deciding anything.
        self._heal_if_expired(now)

        if self._locked_user_id is None:
            # No active lock: pass the audio. The caller is expected
            # to drive a Stage 1 detector and call ``lock_to`` on the
            # first identified utterance.
            return True

        if user_id is None or user_id != self._locked_user_id:
            return False

        # Locked user activity: extend the timeout.
        self._last_activity_at = now
        return True

    def can_approve(self, user_id: str | None, now: datetime) -> bool:
        """Voice approval channel hook: only the locked user can approve.

        ``user_id=None`` (Voice ID failed) always returns False — sir's
        PIN/passphrase fallback is the other branch and lives in step
        5.11.
        """
        self._heal_if_expired(now)
        if self._locked_user_id is None or user_id is None:
            return False
        return user_id == self._locked_user_id

    # ── inspection ────────────────────────────────────────────────

    def state(self, now: datetime | None = None) -> LockState:
        """Snapshot of the lock; heals any expired lock first."""
        if now is not None:
            self._heal_if_expired(now)
        return LockState(
            locked_user_id=self._locked_user_id,
            locked_at=self._locked_at,
            last_activity_at=self._last_activity_at,
            timeout_seconds=self.config.timeout_seconds,
        )

    @property
    def is_locked(self) -> bool:
        return self._locked_user_id is not None

    # ── internals ─────────────────────────────────────────────────

    def _heal_if_expired(self, now: datetime) -> None:
        if self._locked_user_id is None or self._last_activity_at is None:
            return
        elapsed = now - self._last_activity_at
        if elapsed >= timedelta(seconds=self.config.timeout_seconds):
            log.info(
                "session lock expired after %.1f s of silence; releasing %r",
                elapsed.total_seconds(),
                self._locked_user_id,
            )
            self.clear()


__all__ = ["LockState", "SessionLock"]
