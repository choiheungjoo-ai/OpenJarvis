"""Delivery channel ABC + multi-channel dispatcher.

The ABC keeps Newton's surfaces (CLI today, desktop today, voice in
block 5, HUD in block 11) interchangeable. The dispatcher is the
piece the daemon and the ``watch`` command call: it asks each channel
in turn to deliver a notification and tracks already-delivered ids
so the same row isn't shown twice within the same process lifetime.

We don't add a ``delivered_at`` column. Auto-ignore (step 4.6, default
5 min grace) provides the long-horizon deduplication: a row that aged
out has ``user_response='ignored'`` and is filtered out of the
"pending" query the watcher uses. Within the watch loop's lifetime,
the in-process ``seen`` set takes care of repeats.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from newton.models.proactive_notification import ProactiveNotification


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    """Per-channel delivery outcome."""

    channel: str
    delivered: bool
    note: str | None = None


class DeliveryChannel(ABC):
    """One surface that can show sir a notification."""

    #: Stable identifier — used for logging and for filtering channels
    #: in the dispatcher.
    name: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if getattr(cls, "__abstractmethods__", None):
            return
        if not getattr(cls, "name", None):
            raise TypeError(f"{cls.__name__}: DeliveryChannel subclass needs a name")

    @abstractmethod
    def deliver(self, notification: ProactiveNotification) -> DeliveryResult:
        """Render the notification on this surface.

        Implementations MUST surface text via
        :func:`newton.proactive.alerts.display_text` — the storage
        ``[kind]`` prefix is never user-facing.
        """


@dataclass
class DeliveryDispatcher:
    """Fan out a notification to every registered channel, dedupe by id."""

    channels: list[DeliveryChannel] = field(default_factory=list)
    _seen: set[int] = field(default_factory=set)

    def add(self, channel: DeliveryChannel) -> None:
        self.channels.append(channel)

    def deliver(self, notification: ProactiveNotification) -> list[DeliveryResult]:
        if notification.notification_id in self._seen:
            return [
                DeliveryResult(channel=c.name, delivered=False, note="already shown")
                for c in self.channels
            ]
        results = [c.deliver(notification) for c in self.channels]
        # Mark seen only if *some* channel actually delivered; otherwise
        # the next pass will try again.
        if any(r.delivered for r in results):
            self._seen.add(notification.notification_id)
        return results

    def forget(self, notification_id: int) -> None:
        """Allow re-delivery of one id; useful for tests."""
        self._seen.discard(notification_id)


__all__ = [
    "DeliveryChannel",
    "DeliveryDispatcher",
    "DeliveryResult",
]
