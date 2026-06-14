"""Proactive notification scheduler — block 4 step 4.5.

The scheduler turns the anticipation engine's ranked predictions into
``proactive_notifications`` rows, applying three additional gates that
the engine itself doesn't enforce:

    1. **Off mode → skip.** The engine already filters by the mode
       threshold, but for telemetry we want to log "off" as the
       skip reason rather than "no predictions crossed."
    2. **Quiet hours → skip** (unless the prediction is marked
       ``urgent``; step 4.5 doesn't ship an urgent path yet but the
       parameter is in place so step 4.6's rejection-learning rows
       and future calendar alerts can override).
    3. **Per-pattern cooldown → skip.** Once a pattern fires, the
       same pattern is suppressed for ``pattern_cooldown_minutes``
       — keyed on ``trigger_pattern_id``, not the ``[kind]`` prefix
       (alerts already have that, and scheduler rows carry a real
       FK).

Rows are written via ``ProactiveNotification`` with ``trigger_pattern_id``
set and ``sent_at`` pinned to the same ``now`` the scheduler used —
mirrors the timezone-safe choice in ``AlertChecker``. No ``[kind]``
prefix on scheduler-driven text; ``display_text`` becomes a no-op
pass-through for these rows, which is fine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from newton.models.proactive_notification import ProactiveNotification
from newton.proactive.anticipation import AnticipationEngine, Prediction
from newton.proactive.config import (
    QuietHoursConfig,
    SchedulerConfig,
    load_proactive_config,
)
from newton.proactive.context import assemble
from newton.proactive.quiet_hours import QuietHoursWindow, parse_hhmm


@dataclass
class ScheduleReport:
    """Summary of one scheduler tick."""

    user_id: str
    mode: str
    scheduled: list[int] = field(default_factory=list)  # notification_ids
    skipped: list[dict] = field(default_factory=list)  # {pattern_id, reason}
    reason: str | None = None  # set when the whole tick short-circuited


@dataclass
class Scheduler:
    """One-shot scheduler driver. Construct per call; the daemon owns timing."""

    config: SchedulerConfig
    engine: AnticipationEngine
    # ``tz_name`` defaults to whatever was passed to the engine; explicit
    # here so the scheduler doesn't have to reach into engine internals.
    tz_name: str = "Asia/Seoul"

    def tick(
        self,
        db_session: Session,
        user_id: str,
        mode: str,
        now: datetime | None = None,
        urgent: bool = False,
    ) -> ScheduleReport:
        if now is None:
            now = datetime.now()

        # Heal expired time-bounded modes before reading anything.
        from newton.proactive.modes import apply_revert_due, resolve_mode

        apply_revert_due(db_session, now=now)

        # Auto-ignore stale notifications first so the penalty in the
        # anticipation predict() below already reflects them.
        from newton.proactive.learning import mark_stale_as_ignored

        mark_stale_as_ignored(db_session, now=now)

        # If the caller didn't pin the mode, read the user's stored
        # ``users.proactive_mode`` column. CLI surfaces still allow an
        # explicit ``--mode`` override; passing it through here just
        # bypasses the lookup.
        if mode == "__auto__":
            mode = resolve_mode(
                db_session,
                user_id,
                default=self.engine.config.default_mode,
                now=now,
            ).mode
        report = ScheduleReport(user_id=user_id, mode=mode)

        if mode == "off":
            report.reason = "mode=off"
            return report

        window = self._quiet_window(self.config.quiet_hours)
        if not urgent and window.is_quiet(now):
            report.reason = "quiet_hours"
            return report

        # The engine reads patterns and applies its mode threshold.
        # We give it a context built right here so the assembled
        # recent_runs and the cooldown query agree on `now`.
        ctx = assemble(
            db_session,
            user_id,
            now=now,
            lookback_seconds=self.engine.config.sequence_relevance_seconds,
        )
        predictions = self.engine.predict(db_session, ctx, mode=mode)

        written = 0
        for pred in predictions:
            if written >= self.config.max_per_tick:
                report.skipped.append(
                    {"pattern_id": pred.pattern_id, "reason": "max_per_tick"}
                )
                continue
            if self._in_cooldown(db_session, user_id, pred.pattern_id, now):
                report.skipped.append(
                    {"pattern_id": pred.pattern_id, "reason": "pattern_cooldown"}
                )
                continue

            row = self._insert_row(db_session, user_id, pred, now)
            report.scheduled.append(row.notification_id)
            written += 1

        return report

    # ── helpers ──────────────────────────────────────────────────────

    def _quiet_window(self, cfg: QuietHoursConfig) -> QuietHoursWindow:
        return QuietHoursWindow(
            start=parse_hhmm(cfg.start),
            end=parse_hhmm(cfg.end),
            tz_name=self.tz_name,
        )

    def _in_cooldown(
        self,
        db_session: Session,
        user_id: str,
        pattern_id: int,
        now: datetime,
    ) -> bool:
        if self.config.pattern_cooldown_minutes <= 0:
            return False
        cutoff = now - timedelta(minutes=self.config.pattern_cooldown_minutes)
        hit = db_session.execute(
            select(ProactiveNotification.notification_id)
            .where(
                ProactiveNotification.user_id == user_id,
                ProactiveNotification.trigger_pattern_id == pattern_id,
                ProactiveNotification.sent_at > cutoff,
            )
            .limit(1)
        ).first()
        return hit is not None

    @staticmethod
    def _insert_row(
        db_session: Session,
        user_id: str,
        prediction: Prediction,
        now: datetime,
    ) -> ProactiveNotification:
        row = ProactiveNotification(
            user_id=user_id,
            trigger_pattern_id=prediction.pattern_id,
            notification_text=prediction.notification_text,
            sent_at=now,
        )
        db_session.add(row)
        db_session.flush()
        return row


def build_default_scheduler(tz_name: str | None = None) -> Scheduler:
    """Wire up a Scheduler from the live YAML config."""
    cfg = load_proactive_config()
    engine = AnticipationEngine(
        config=cfg.anticipation,
        pattern_timezone=cfg.patterns.pattern_timezone,
    )
    return Scheduler(
        config=cfg.scheduler,
        engine=engine,
        tz_name=tz_name or cfg.patterns.pattern_timezone,
    )


__all__ = ["ScheduleReport", "Scheduler", "build_default_scheduler"]
