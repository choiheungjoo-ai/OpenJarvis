"""Desktop delivery channel — ``notify-send`` on Linux/WSL2.

When ``notify-send`` isn't available (CI, headless servers, missing
package), the channel reports ``delivered=False`` with a note. The
dispatcher dedupe set only adds an id when *some* channel delivered,
so a desktop miss won't suppress later attempts.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass

from newton.models.proactive_notification import ProactiveNotification
from newton.proactive.alerts import display_text
from newton.proactive.delivery.base import DeliveryChannel, DeliveryResult

log = logging.getLogger(__name__)


@dataclass
class DesktopDeliveryChannel(DeliveryChannel):
    """Shell out to ``notify-send``. Best-effort."""

    name: str = "desktop"
    app_name: str = "Newton"
    urgency: str = "normal"  # 'low' / 'normal' / 'critical'
    # Injectable for tests; defaults to the real binary lookup.
    notify_send_path: str | None = None

    def _resolve_binary(self) -> str | None:
        if self.notify_send_path is not None:
            return self.notify_send_path or None
        return shutil.which("notify-send")

    def deliver(self, notification: ProactiveNotification) -> DeliveryResult:
        binary = self._resolve_binary()
        if not binary:
            return DeliveryResult(
                channel=self.name,
                delivered=False,
                note="notify-send not available",
            )
        text = display_text(notification.notification_text)
        try:
            subprocess.run(  # noqa: S603 — argv is fixed and safe
                [
                    binary,
                    "--app-name",
                    self.app_name,
                    "--urgency",
                    self.urgency,
                    "Newton",
                    text,
                ],
                check=False,
                capture_output=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("desktop deliver failed: %s", e)
            return DeliveryResult(
                channel=self.name,
                delivered=False,
                note=str(e),
            )
        return DeliveryResult(channel=self.name, delivered=True)


__all__ = ["DesktopDeliveryChannel"]
