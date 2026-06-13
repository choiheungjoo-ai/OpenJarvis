"""Threshold-based alerts — block 4 step 4.2.

The simplest possible proactive behaviour: when the most recent value of
a metric crosses a configured threshold, insert a row into
``proactive_notifications``. Delivery is step 4.7; pattern learning is
step 4.3+. This step just gets useful rows into the table.

Storage encoding — the ``[kind]`` prefix
-----------------------------------------
The ``proactive_notifications`` schema has no ``kind`` column, but
cooldown ("don't fire ``cpu_high`` again within 15 minutes") needs to
identify *which* rule raised a row. We solve this without a migration by
prefixing the stored ``notification_text`` with ``[kind] ``, e.g.::

    "[cpu_high] Sir, CPU at 95%."

The prefix is **storage-only**. It must never reach the user.
:func:`display_text` strips it; every code path that surfaces a
notification (CLI, voice in block 5, desktop in step 4.7) must go through
that helper. Tests assert the bare text is what reaches users.

The ``status: pending`` lifecycle the design doc mentions is implicit in
the schema: a freshly-inserted row has ``user_response IS NULL`` and
``response_at IS NULL`` — that *is* pending. Step 4.5's scheduler may
introduce an explicit status column later; this step doesn't need one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from newton.models.proactive_notification import ProactiveNotification
from newton.models.system_metric import SystemMetric
from newton.proactive.config import (
    ProactiveConfig,
    ThresholdRule,
    load_proactive_config,
)

# ─────────────────────────────────────────────────────────────────────────────
# Prefix encoding
# ─────────────────────────────────────────────────────────────────────────────

# Anchored at the start; matches a single ``[kind]`` token followed by
# exactly one space. The kind itself is restricted to lowercase letters,
# digits, and underscores (ThresholdRule._kind_is_identifier enforces
# the same alphabet at config-load time).
_ALERT_PREFIX_RE = re.compile(r"^\[([a-z0-9_]+)\]\s")


def _store_text(kind: str, text: str) -> str:
    """Build the storage form: ``[kind] <user-facing text>``."""
    return f"[{kind}] {text}"


def display_text(stored: str) -> str:
    """Strip the storage-only ``[kind]`` prefix from a notification row.

    Every surface that shows or speaks a notification must call this.
    A stored string with no prefix (e.g. a future row written by a
    different code path) is returned unchanged.
    """
    return _ALERT_PREFIX_RE.sub("", stored, count=1)


def extract_kind(stored: str) -> str | None:
    """Return the ``kind`` token from a stored row, or ``None`` if absent."""
    match = _ALERT_PREFIX_RE.match(stored)
    return match.group(1) if match else None


# ─────────────────────────────────────────────────────────────────────────────
# Checker
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class FiredAlert:
    """One alert raised during a single run of the checker."""

    kind: str
    metric_type: str
    value: float
    stored_text: str

    @property
    def display(self) -> str:
        """User-facing text (with the ``[kind]`` prefix stripped)."""
        return display_text(self.stored_text)


@dataclass
class AlertChecker:
    """Evaluate threshold rules against the latest samples, insert rows.

    Construct with a config (or take the loaded defaults), then call
    :meth:`run` once per daemon tick. The checker is stateless apart
    from its config; cooldown is tracked entirely via the existence
    of recent rows in ``proactive_notifications``.
    """

    config: ProactiveConfig = field(default_factory=load_proactive_config)

    # ── single-rule helpers (broken out for unit testing) ──────────────

    def _latest_value(
        self,
        session: Session,
        metric_type: str,
    ) -> float | None:
        """Return the value of the most recent sample of ``metric_type``, or None."""
        row = session.execute(
            select(SystemMetric.value)
            .where(SystemMetric.metric_type == metric_type)
            .order_by(SystemMetric.captured_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return float(row) if row is not None else None

    def _crosses(self, rule: ThresholdRule, value: float) -> bool:
        if rule.op == ">":
            return value > rule.value
        if rule.op == "<":
            return value < rule.value
        # Pydantic Literal validation rules this out at config-load time;
        # defensive default keeps a future op addition from silently
        # firing.
        return False

    def _in_cooldown(
        self,
        session: Session,
        user_id: str,
        kind: str,
        now: datetime,
    ) -> bool:
        """True if a row with this kind exists within ``cooldown_minutes``."""
        if self.config.cooldown_minutes <= 0:
            return False
        cutoff = now - timedelta(minutes=self.config.cooldown_minutes)
        hit = session.execute(
            select(ProactiveNotification.notification_id)
            .where(
                ProactiveNotification.user_id == user_id,
                ProactiveNotification.notification_text.like(f"[{kind}] %"),
                ProactiveNotification.sent_at > cutoff,
            )
            .limit(1)
        ).first()
        return hit is not None

    # ── main entry point ───────────────────────────────────────────────

    def run(
        self,
        session: Session,
        user_id: str,
        now: datetime | None = None,
    ) -> list[FiredAlert]:
        """Evaluate every non-dormant rule. Insert rows for fresh fires.

        Returns the list of alerts that actually fired (i.e. crossed the
        threshold AND were past cooldown). The caller owns the session;
        the checker only ``session.add()``s rows.

        ``now`` is injectable for deterministic cooldown tests.
        """
        if now is None:
            now = datetime.now()

        fired: list[FiredAlert] = []

        for rule in self.config.thresholds:
            if rule.dormant:
                continue

            value = self._latest_value(session, rule.metric_type)
            if value is None:
                continue
            if not self._crosses(rule, value):
                continue
            if self._in_cooldown(session, user_id, rule.kind, now):
                continue

            stored = _store_text(rule.kind, rule.text.format(value=value))
            session.add(
                ProactiveNotification(
                    user_id=user_id,
                    notification_text=stored,
                    # Pin sent_at to the checker's clock so the cooldown
                    # comparison reads the same time domain as this
                    # insert. The server default (SQLite CURRENT_TIMESTAMP,
                    # which is UTC) would otherwise disagree with a
                    # local-time ``datetime.now()`` on hosts where the
                    # two diverge by more than the cooldown window.
                    sent_at=now,
                )
            )
            fired.append(
                FiredAlert(
                    kind=rule.kind,
                    metric_type=rule.metric_type,
                    value=value,
                    stored_text=stored,
                )
            )

        return fired


__all__ = [
    "AlertChecker",
    "FiredAlert",
    "display_text",
    "extract_kind",
]
