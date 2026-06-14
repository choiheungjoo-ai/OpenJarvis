"""Voice delivery channel — Block 4's DeliveryChannel implemented in voice.

The scheduler (step 4.5) writes ``proactive_notifications`` rows; the
delivery dispatcher (step 4.7) iterates them. This channel makes
Newton *speak* the row in the relevant persona's voice.

The block-4 ABC is **synchronous** (``deliver(notification) -> DeliveryResult``);
the voice stack is async-friendly. We bridge by accepting a synchronous
``speaker`` callable that the runtime supplies — it can run an
``asyncio.run_until_complete`` internally or be a real ``threading.Thread``-
based wrapper. The runtime owns that policy; this channel doesn't impose
one.

[kind] and [recall:N] markers are stripped via the block-4
:func:`display_text` helper so sir hears the same prose the CLI prints.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from newton.models.proactive_notification import ProactiveNotification
from newton.proactive.alerts import display_text
from newton.proactive.delivery.base import DeliveryChannel, DeliveryResult

log = logging.getLogger(__name__)


class VoiceDeliveryChannel(DeliveryChannel):
    """Speak proactive notifications via the TTS stack."""

    name = "voice"

    def __init__(
        self,
        speaker: Callable[[str, str | None, str | None], bool],
        *,
        persona_id: str = "jarvis",
        language: str | None = None,
    ) -> None:
        """``speaker`` returns True if it actually played audio.

        Signature: ``speaker(text, persona_id, language) -> bool``.
        The runtime adapter wraps the async TTS / fallback chain with
        a thread + event-loop boundary. For tests we pass a tiny
        synchronous fake.
        """
        self._speaker = speaker
        self._persona = persona_id
        self._language = language

    def deliver(self, notification: ProactiveNotification) -> DeliveryResult:
        text = display_text(notification.notification_text)
        try:
            delivered = bool(self._speaker(text, self._persona, self._language))
        except Exception as e:  # noqa: BLE001
            log.warning("voice deliver failed: %s", e)
            return DeliveryResult(
                channel=self.name, delivered=False, note=type(e).__name__
            )
        if not delivered:
            return DeliveryResult(
                channel=self.name, delivered=False, note="speaker returned False"
            )
        return DeliveryResult(channel=self.name, delivered=True)


__all__ = ["VoiceDeliveryChannel"]
