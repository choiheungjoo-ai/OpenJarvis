"""CLI delivery channel — prints to the active watch stream."""

from __future__ import annotations

import sys
from typing import TextIO

from newton.models.proactive_notification import ProactiveNotification
from newton.proactive.alerts import display_text
from newton.proactive.delivery.base import DeliveryChannel, DeliveryResult


class CLIDeliveryChannel(DeliveryChannel):
    """Write the notification to a stream (stdout by default).

    The watcher process owns the stream. When sir is *not* watching
    we still mark delivered = True because the call site (the
    dispatcher) is what decides to route to this channel — the row
    is in the DB either way and ``proactive notifications`` will
    surface it later. A channel that says "delivered = False"
    because there's nobody at the terminal would force the
    dispatcher to retry forever.
    """

    name = "cli"

    def __init__(self, stream: TextIO | None = None) -> None:
        # Default constructed lazily so tests can pass a StringIO and
        # not depend on stdout flushing semantics.
        self._stream = stream

    def _resolve_stream(self) -> TextIO:
        return self._stream if self._stream is not None else sys.stdout

    def deliver(self, notification: ProactiveNotification) -> DeliveryResult:
        text = display_text(notification.notification_text)
        ts = notification.sent_at.strftime("%H:%M:%S") if notification.sent_at else "—"
        line = f"[{ts}] #{notification.notification_id} {text}\n"
        stream = self._resolve_stream()
        stream.write(line)
        stream.flush()
        return DeliveryResult(channel=self.name, delivered=True)


__all__ = ["CLIDeliveryChannel"]
