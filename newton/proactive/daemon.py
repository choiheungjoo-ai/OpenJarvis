"""Long-running monitoring daemon — block 4 step 4.1.

A ``ProactiveDaemon`` runs the simplest possible loop: every *N*
seconds, ask each registered ``Monitor`` for a sample, and write each
non-``None`` reading into ``system_metrics``. *N* is adaptive: short
(default 5 s) when the user is "active", long (default 60 s) when
idle. The active/idle decision is supplied as a callable so this file
holds no policy about it — step 4.5's scheduler can swap in a richer
signal without touching the daemon.

Lifecycle:

    * :meth:`run_forever` blocks until :meth:`stop` is called from
      another thread (or a SIGTERM / SIGINT handler — see
      :meth:`install_signal_handlers`). Use :meth:`tick_once` for tests
      and for the ``--once`` CLI smoke path; it runs exactly one
      sampling pass with no sleep.
    * Shutdown latency is bounded by ``shutdown_slice_s`` (default
      0.5 s) regardless of the sampling interval, because the daemon
      sleeps in slices and re-checks the stop event between them.

Thread-safety: the daemon is single-threaded; the only cross-thread
mechanism is :attr:`stop_event`. Tests drive it from the test thread,
``stop()`` is safe from a signal handler.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from newton.db import get_session
from newton.models.chat_session import ChatSession
from newton.models.system_metric import SystemMetric
from newton.proactive.alerts import AlertChecker, FiredAlert
from newton.proactive.monitors import Monitor, default_monitors

log = logging.getLogger(__name__)


# Default "is the user active right now?" predicate. Any open session
# (``ended_at IS NULL``) counts as active. Cheap query — single index
# scan — but still wrapped behind a callable so step 4.5 can replace it
# without touching this module.
def default_is_active() -> bool:
    """Return True when at least one session has ``ended_at IS NULL``."""
    with get_session() as session:
        stmt = (
            select(ChatSession.session_id)
            .where(ChatSession.ended_at.is_(None))
            .limit(1)
        )
        return session.execute(stmt).first() is not None


IsActive = Callable[[], bool]


@dataclass
class TickReport:
    """Summary of one sampling pass — what we wrote, what was unavailable."""

    metrics_written: int = 0
    metrics_skipped: int = 0
    per_monitor: dict[str, float | None] = field(default_factory=dict)
    alerts_fired: list[FiredAlert] = field(default_factory=list)
    scheduled_ids: list[int] = field(default_factory=list)


@dataclass
class ProactiveDaemon:
    """Adaptive monitoring loop.

    Construct with the monitor list and the active/idle predicate; call
    :meth:`run_forever` to block, or :meth:`tick_once` for a single
    pass.
    """

    monitors: list[Monitor] = field(default_factory=default_monitors)
    is_active: IsActive = field(default=default_is_active)
    active_interval_s: float = 5.0
    idle_interval_s: float = 60.0
    shutdown_slice_s: float = 0.5

    # Optional alert checker. ``None`` keeps the daemon a pure sampler
    # (the original step 4.1 behaviour and what unit tests of monitors
    # need). When supplied, each tick runs the checker after sampling,
    # in the same transaction, so the freshly-written system_metrics row
    # is what the checker reads.
    alert_checker: AlertChecker | None = None
    alert_user_id: str = "sir"

    # Optional notification scheduler (step 4.5). Runs after alerts so
    # both surfaces see the same fresh metrics inside one transaction.
    # When ``None``, the daemon is back to "sampler + alerts only".
    scheduler: object | None = None
    scheduler_mode: str = "smart"

    stop_event: threading.Event = field(default_factory=threading.Event)

    # Re-entrancy guard: signal handlers installed twice on the same
    # daemon would chain, with surprising semantics.
    _signal_handlers_installed: bool = False

    # ── sampling ────────────────────────────────────────────────────────

    def tick_once(self, db_session: Session | None = None) -> TickReport:
        """Sample every monitor once and persist the results.

        If ``db_session`` is supplied (tests pass one for transactional
        isolation), it is used and *not* committed — the caller owns
        the lifecycle. Otherwise a fresh session is opened, committed,
        and closed.
        """
        report = TickReport()

        if db_session is not None:
            self._sample_into(db_session, report)
            return report

        with get_session() as session:
            self._sample_into(session, report)
        return report

    def _sample_into(self, session: Session, report: TickReport) -> None:
        for monitor in self.monitors:
            try:
                value = monitor.sample()
            except Exception as e:  # noqa: BLE001
                # A misbehaving monitor must not take down the loop.
                log.warning("monitor %s raised: %s", monitor.name, e)
                value = None

            report.per_monitor[monitor.name] = value
            if value is None:
                report.metrics_skipped += 1
                continue

            session.add(
                SystemMetric(metric_type=monitor.metric_type, value=float(value))
            )
            report.metrics_written += 1

        if self.alert_checker is not None:
            # Flush the metric inserts so the checker's "latest sample"
            # query reads what this tick produced rather than the
            # previous tick's values.
            session.flush()
            try:
                report.alerts_fired = self.alert_checker.run(
                    session, self.alert_user_id
                )
            except Exception as e:  # noqa: BLE001
                # An alert misfire must not take down the sampling loop —
                # log it and let the next tick try again.
                log.warning("alert checker failed: %s", e)

        if self.scheduler is not None:
            session.flush()
            try:
                sched_report = self.scheduler.tick(
                    session, self.alert_user_id, self.scheduler_mode
                )
                report.scheduled_ids = list(sched_report.scheduled)
            except Exception as e:  # noqa: BLE001
                log.warning("scheduler tick failed: %s", e)

    # ── interval policy ────────────────────────────────────────────────

    def next_interval(self) -> float:
        """Return the sleep duration before the next tick, based on activity."""
        try:
            active = bool(self.is_active())
        except Exception as e:  # noqa: BLE001
            # If the predicate itself fails, fall back to the safer (longer)
            # idle interval — better to under-sample than to spin.
            log.warning("is_active predicate raised: %s; treating as idle", e)
            return self.idle_interval_s
        return self.active_interval_s if active else self.idle_interval_s

    # ── main loop ──────────────────────────────────────────────────────

    def run_forever(self) -> None:
        """Block until :meth:`stop` is called.

        Each iteration: sample once, then sleep in ``shutdown_slice_s``
        slices up to the current interval — so SIGTERM during a 60 s
        idle sleep still shuts us down within one slice.
        """
        log.info(
            "proactive daemon started — %d monitor(s), active=%.0fs idle=%.0fs",
            len(self.monitors),
            self.active_interval_s,
            self.idle_interval_s,
        )
        try:
            while not self.stop_event.is_set():
                try:
                    self.tick_once()
                except Exception as e:  # noqa: BLE001
                    # DB connection blips etc. shouldn't kill the daemon;
                    # log and try again next interval.
                    log.exception("tick failed: %s", e)

                self._sleep_with_shutdown(self.next_interval())
        finally:
            log.info("proactive daemon stopped")

    def _sleep_with_shutdown(self, interval_s: float) -> None:
        """Sleep up to ``interval_s``, returning early if stop is set."""
        slice_s = max(0.05, min(self.shutdown_slice_s, interval_s))
        deadline = time.monotonic() + interval_s
        while not self.stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(slice_s, remaining))

    # ── shutdown plumbing ──────────────────────────────────────────────

    def stop(self) -> None:
        """Request a graceful shutdown. Safe from signal handlers."""
        self.stop_event.set()

    def install_signal_handlers(self) -> None:
        """Wire SIGTERM and SIGINT to :meth:`stop`.

        Must be called from the main thread (Python's signal module
        rejects handlers installed elsewhere). Idempotent on the same
        instance.
        """
        if self._signal_handlers_installed:
            return

        def _handle(signum, _frame):  # noqa: ANN001
            log.info("received signal %d; shutting down", signum)
            self.stop()

        signal.signal(signal.SIGTERM, _handle)
        signal.signal(signal.SIGINT, _handle)
        self._signal_handlers_installed = True


__all__ = ["IsActive", "ProactiveDaemon", "TickReport", "default_is_active"]
