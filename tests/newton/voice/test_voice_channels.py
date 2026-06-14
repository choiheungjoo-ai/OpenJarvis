"""Tests for VoiceApprovalChannel + VoiceDeliveryChannel + parse_yes_no."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from newton.models.proactive_notification import ProactiveNotification
from newton.proactive.delivery.base import DeliveryResult
from newton.tools.approval import ApprovalRequest
from newton.voice.approval_channel import VoiceApprovalChannel, parse_yes_no
from newton.voice.config import SessionLockConfig
from newton.voice.delivery_channel import VoiceDeliveryChannel
from newton.voice.session_lock import SessionLock

# ── parse_yes_no ─────────────────────────────────────────────────────────


def test_parse_yes_no_yes_words():
    for word in ["yes", "yeah", "approve", "네", "응"]:
        assert parse_yes_no(word) == "approved"


def test_parse_yes_no_no_words():
    for word in ["no", "deny", "stop", "아니", "아니요"]:
        assert parse_yes_no(word) == "denied"


def test_parse_yes_no_ambiguous_when_empty():
    assert parse_yes_no("   ") == "ambiguous"


def test_parse_yes_no_ambiguous_when_both():
    assert parse_yes_no("yes no") == "ambiguous"


def test_parse_yes_no_case_insensitive():
    assert parse_yes_no("YES sir") == "approved"


def test_parse_yes_no_strips_punctuation():
    assert parse_yes_no("yes, sure") == "approved"


# ── VoiceApprovalChannel ─────────────────────────────────────────────────


T0 = datetime(2026, 6, 14, 12, 0, 0)


def _approval_req(user_id: str = "sir") -> ApprovalRequest:
    return ApprovalRequest(
        tool_name="echo_to_file",
        risk_level=2,
        persona_id="jarvis",
        user_id=user_id,
        args_summary="hi",
        policy_source="risk_default",
    )


@pytest.mark.asyncio
async def test_voice_approval_speaks_and_listens():
    spoken: list[tuple[str, str, str | None]] = []

    async def speaker(text, persona, language):
        spoken.append((text, persona, language))

    async def listener(_timeout):
        return "yes"

    lock = SessionLock(config=SessionLockConfig(timeout_seconds=30))
    lock.lock_to("sir", T0)
    ch = VoiceApprovalChannel(
        speaker=speaker,
        listener=listener,
        session_lock=lock,
        now=lambda: T0 + timedelta(seconds=5),
    )
    outcome = await ch.request(_approval_req())
    assert outcome.approved is True
    assert outcome.decision == "approved"
    assert len(spoken) == 1
    assert "echo_to_file" in spoken[0][0]


@pytest.mark.asyncio
async def test_voice_approval_denies_on_no():
    async def speaker(*_a, **_kw):
        return

    async def listener(_timeout):
        return "no, stop"

    lock = SessionLock(config=SessionLockConfig(timeout_seconds=30))
    lock.lock_to("sir", T0)
    ch = VoiceApprovalChannel(
        speaker=speaker,
        listener=listener,
        session_lock=lock,
        now=lambda: T0 + timedelta(seconds=5),
    )
    outcome = await ch.request(_approval_req())
    assert outcome.approved is False
    assert outcome.decision == "denied"


@pytest.mark.asyncio
async def test_voice_approval_refused_when_session_not_locked():
    async def speaker(*_a, **_kw):
        raise AssertionError("must not speak when refused")

    async def listener(_timeout):
        raise AssertionError("must not listen when refused")

    lock = SessionLock(config=SessionLockConfig(timeout_seconds=30))
    # Lock to gf, but approval requested for sir → refused.
    lock.lock_to("gf", T0)
    ch = VoiceApprovalChannel(
        speaker=speaker,
        listener=listener,
        session_lock=lock,
        now=lambda: T0 + timedelta(seconds=5),
    )
    outcome = await ch.request(_approval_req(user_id="sir"))
    assert outcome.approved is False
    assert outcome.reason == "session_not_locked"


@pytest.mark.asyncio
async def test_voice_approval_timeout_returns_timeout_decision():
    async def speaker(*_a, **_kw):
        return

    async def listener(_timeout):
        raise TimeoutError()

    lock = SessionLock(config=SessionLockConfig(timeout_seconds=30))
    lock.lock_to("sir", T0)
    ch = VoiceApprovalChannel(
        speaker=speaker,
        listener=listener,
        session_lock=lock,
        now=lambda: T0,
    )
    outcome = await ch.request(_approval_req())
    assert outcome.decision == "timeout"
    assert outcome.approved is False


@pytest.mark.asyncio
async def test_voice_approval_ambiguous_is_denied():
    async def speaker(*_a, **_kw):
        return

    async def listener(_timeout):
        return "uhhhh"  # not yes, not no

    lock = SessionLock(config=SessionLockConfig(timeout_seconds=30))
    lock.lock_to("sir", T0)
    ch = VoiceApprovalChannel(
        speaker=speaker,
        listener=listener,
        session_lock=lock,
        now=lambda: T0,
    )
    outcome = await ch.request(_approval_req())
    assert outcome.approved is False
    assert "ambiguous" in (outcome.reason or "")


def test_voice_approval_name():
    ch = VoiceApprovalChannel(
        speaker=lambda *a: None,  # type: ignore[arg-type]
        listener=lambda *a: None,  # type: ignore[arg-type]
        session_lock=SessionLock(config=SessionLockConfig(timeout_seconds=30)),
    )
    assert ch.name == "voice"


# ── VoiceDeliveryChannel ────────────────────────────────────────────────


def _notif(text: str = "[cpu_high] Sir, CPU at 95%.") -> ProactiveNotification:
    n = ProactiveNotification(
        user_id="sir",
        notification_text=text,
        sent_at=T0,
    )
    n.notification_id = 1
    return n


def test_voice_delivery_strips_kind_prefix_before_speaking():
    spoken: list[tuple[str, str, str | None]] = []

    def speaker(text, persona, language):
        spoken.append((text, persona, language))
        return True

    ch = VoiceDeliveryChannel(speaker=speaker)
    result = ch.deliver(_notif(text="[cpu_high] Sir, CPU at 95%."))
    assert result.delivered is True
    assert spoken == [("Sir, CPU at 95%.", "jarvis", None)]


def test_voice_delivery_strips_recall_marker():
    spoken: list[str] = []

    def speaker(text, _persona, _language):
        spoken.append(text)
        return True

    ch = VoiceDeliveryChannel(speaker=speaker)
    ch.deliver(_notif(text="[recall:42] Sir, last time you decided X."))
    assert spoken == ["Sir, last time you decided X."]


def test_voice_delivery_speaker_returning_false_marks_undelivered():
    ch = VoiceDeliveryChannel(speaker=lambda *_a: False)
    result = ch.deliver(_notif())
    assert result.delivered is False
    assert "False" in (result.note or "")


def test_voice_delivery_speaker_exception_is_caught():
    def speaker(*_a, **_kw):
        raise RuntimeError("audio device busy")

    ch = VoiceDeliveryChannel(speaker=speaker)
    result = ch.deliver(_notif())
    assert result.delivered is False
    assert "RuntimeError" in (result.note or "")


def test_voice_delivery_channel_name():
    ch = VoiceDeliveryChannel(speaker=lambda *_a: True)
    assert ch.name == "voice"
    assert isinstance(ch.deliver(_notif()), DeliveryResult)


def test_voice_delivery_persona_and_language_passed_through():
    spoken: list[tuple[str, str, str | None]] = []

    def speaker(text, persona, language):
        spoken.append((text, persona, language))
        return True

    ch = VoiceDeliveryChannel(speaker=speaker, persona_id="friday", language="ko")
    ch.deliver(_notif(text="안녕하십니까."))
    assert spoken == [("안녕하십니까.", "friday", "ko")]
