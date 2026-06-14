"""Tests for delivery channels — CLI + desktop + dispatcher."""

from __future__ import annotations

import io
import subprocess
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from newton.models.proactive_notification import ProactiveNotification
from newton.proactive.delivery import (
    CLIDeliveryChannel,
    DeliveryDispatcher,
    DesktopDeliveryChannel,
)
from newton.proactive.delivery.base import DeliveryChannel, DeliveryResult


def _notif(
    notification_id: int = 1, text: str = "Sir, status check."
) -> ProactiveNotification:
    n = ProactiveNotification(
        user_id="sir",
        notification_text=text,
        sent_at=datetime(2026, 6, 14, 12, 30, 0),
    )
    n.notification_id = notification_id
    return n


# ── ABC enforcement ────────────────────────────────────────────────────────


def test_channel_subclass_requires_name():
    with pytest.raises(TypeError, match="needs a name"):

        class Nameless(DeliveryChannel):
            name = ""

            def deliver(self, notification):  # noqa: ARG002
                return DeliveryResult(channel="x", delivered=True)


# ── CLIDeliveryChannel ────────────────────────────────────────────────────


def test_cli_channel_writes_to_stream():
    buf = io.StringIO()
    ch = CLIDeliveryChannel(stream=buf)
    res = ch.deliver(_notif(notification_id=42, text="Sir, hello."))
    assert res.delivered is True
    out = buf.getvalue()
    assert "#42" in out
    assert "Sir, hello." in out
    assert "12:30" in out


def test_cli_channel_strips_kind_prefix_via_display_text():
    """Storage form '[kind] body' must render as 'body' only."""
    buf = io.StringIO()
    ch = CLIDeliveryChannel(stream=buf)
    n = _notif(notification_id=7, text="[cpu_high] Sir, CPU at 95%.")
    ch.deliver(n)
    out = buf.getvalue()
    assert "Sir, CPU at 95%." in out
    assert "[cpu_high]" not in out


# ── DesktopDeliveryChannel ────────────────────────────────────────────────


def test_desktop_channel_falls_back_when_binary_absent():
    """An empty string for notify_send_path simulates 'not installed'."""
    ch = DesktopDeliveryChannel(notify_send_path="")
    res = ch.deliver(_notif())
    assert res.delivered is False
    assert "notify-send" in (res.note or "")


def test_desktop_channel_shells_out_correctly():
    ch = DesktopDeliveryChannel(notify_send_path="/usr/bin/notify-send")
    n = _notif(text="Sir, GPU at 90%.")

    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        res = ch.deliver(n)

    assert res.delivered is True
    # The argv we built must include the binary and the user-facing text.
    argv = mock_run.call_args[0][0]
    assert argv[0] == "/usr/bin/notify-send"
    assert "Sir, GPU at 90%." in argv
    # And critically — no [kind] prefix anywhere.
    assert all("[" not in a for a in argv if a.startswith("Sir"))


def test_desktop_channel_strips_kind_prefix():
    ch = DesktopDeliveryChannel(notify_send_path="/usr/bin/notify-send")
    n = _notif(text="[battery_low] Sir, battery at 18%.")

    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        ch.deliver(n)

    argv = mock_run.call_args[0][0]
    assert "Sir, battery at 18%." in argv
    assert not any("[battery_low]" in a for a in argv)


def test_desktop_channel_survives_oserror():
    ch = DesktopDeliveryChannel(notify_send_path="/usr/bin/notify-send")
    with patch.object(subprocess, "run", side_effect=OSError("device busy")):
        res = ch.deliver(_notif())
    assert res.delivered is False
    assert "device busy" in (res.note or "")


# ── DeliveryDispatcher ─────────────────────────────────────────────────────


def test_dispatcher_calls_every_channel():
    buf = io.StringIO()
    dispatcher = DeliveryDispatcher()
    dispatcher.add(CLIDeliveryChannel(stream=buf))
    dispatcher.add(DesktopDeliveryChannel(notify_send_path=""))

    results = dispatcher.deliver(_notif(notification_id=99))

    assert len(results) == 2
    names = {r.channel for r in results}
    assert names == {"cli", "desktop"}


def test_dispatcher_dedupes_after_successful_delivery():
    buf = io.StringIO()
    dispatcher = DeliveryDispatcher()
    dispatcher.add(CLIDeliveryChannel(stream=buf))

    n = _notif(notification_id=1)
    first = dispatcher.deliver(n)
    second = dispatcher.deliver(n)

    assert first[0].delivered is True
    assert second[0].delivered is False
    assert second[0].note == "already shown"


def test_dispatcher_does_not_mark_seen_when_all_channels_failed():
    """If every channel said False, retry on the next pass."""

    class AlwaysFails(DeliveryChannel):
        name = "always_fails"

        def deliver(self, notification):  # noqa: ARG002
            return DeliveryResult(
                channel=self.name, delivered=False, note="never works"
            )

    dispatcher = DeliveryDispatcher()
    dispatcher.add(AlwaysFails())

    n = _notif(notification_id=1)
    dispatcher.deliver(n)
    # Same notification → next deliver should re-attempt, not return "already shown"
    second = dispatcher.deliver(n)
    assert second[0].delivered is False
    assert second[0].note != "already shown"


def test_dispatcher_forget_allows_redelivery():
    buf = io.StringIO()
    dispatcher = DeliveryDispatcher()
    dispatcher.add(CLIDeliveryChannel(stream=buf))

    n = _notif(notification_id=1)
    dispatcher.deliver(n)
    dispatcher.forget(1)
    second = dispatcher.deliver(n)
    assert second[0].delivered is True
