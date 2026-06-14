"""Delivery channels — block 4 step 4.7.

Step 4.7 ships:

    * :class:`DeliveryChannel` — ABC, parallels block 2's
      ``ApprovalChannel`` pattern (one ``deliver`` coroutine that
      returns whether the user saw the message).
    * :class:`CLIDeliveryChannel` — prints to the active
      ``newton proactive watch`` stream.
    * :class:`DesktopDeliveryChannel` — uses ``notify-send`` on
      Linux desktops; falls back to a no-op when the binary is
      absent (e.g. in CI).

Block 5 will add ``VoiceDeliveryChannel`` without touching this
package, by dropping in another :class:`DeliveryChannel` subclass
and registering it.

Critical invariant: every delivery surface displays text through
:func:`newton.proactive.alerts.display_text`. The ``[kind]`` storage
prefix on alert rows must never reach the user — this is the boundary
where that rule is enforced.
"""

from newton.proactive.delivery.base import (
    DeliveryChannel,
    DeliveryDispatcher,
    DeliveryResult,
)
from newton.proactive.delivery.cli import CLIDeliveryChannel
from newton.proactive.delivery.desktop import DesktopDeliveryChannel

__all__ = [
    "CLIDeliveryChannel",
    "DeliveryChannel",
    "DeliveryDispatcher",
    "DeliveryResult",
    "DesktopDeliveryChannel",
]
