"""Voice approval channel — Block 2's ApprovalChannel implemented in voice.

Plugs into the block-2 dispatch path without touching policy or
audit log. When a gated tool call hits this channel, Newton:

    1. Speaks the approval prompt in the persona's voice.
    2. Listens for sir's response (the runtime supplies the listener).
    3. Parses yes / no and returns an ``ApprovalOutcome``.

The session lock (step 5.10) gates *who* may approve: only the
locked user. Voice-ID-failed (user_id=None) callers fall back to
PIN / passphrase (step 5.11). 5.13 ships the channel; the runtime
that wires session_lock + STT + TTS lives in a later step.

Dependencies are all injected:

    speaker(text, persona_id, language) -> awaitable[None]
        How does this channel make Newton say the prompt?

    listener(timeout_seconds) -> awaitable[str]
        How does it get sir's transcript? Step 5.7's WhisperSTT
        usually, but a stub in tests.

    session_lock
        SessionLock from step 5.10 — used to verify ``can_approve``.

That way the channel itself is testable without a real mic.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

from newton.tools.approval import (
    ApprovalChannel,
    ApprovalOutcome,
    ApprovalRequest,
)
from newton.voice.session_lock import SessionLock

log = logging.getLogger(__name__)


#: Conservative defaults — sir can override at construction.
_DEFAULT_YES = ("yes", "yeah", "yep", "sure", "approve", "approved", "네", "응", "좋아")
_DEFAULT_NO = ("no", "nope", "deny", "denied", "stop", "아니", "아니요")


def parse_yes_no(
    transcript: str,
    *,
    yes_words: tuple[str, ...] = _DEFAULT_YES,
    no_words: tuple[str, ...] = _DEFAULT_NO,
) -> str:
    """Return ``"approved"``, ``"denied"``, or ``"ambiguous"``."""
    text = transcript.strip().lower()
    if not text:
        return "ambiguous"
    tokens = set(text.replace(",", " ").split())
    yes_hit = bool(tokens & {y.lower() for y in yes_words})
    no_hit = bool(tokens & {n.lower() for n in no_words})
    if yes_hit and not no_hit:
        return "approved"
    if no_hit and not yes_hit:
        return "denied"
    return "ambiguous"


class VoiceApprovalChannel(ApprovalChannel):
    """Voice-driven approval. Plugs into block-2 dispatch."""

    name = "voice"

    def __init__(
        self,
        speaker: Callable[[str, str, str | None], Awaitable[None]],
        listener: Callable[[float], Awaitable[str]],
        session_lock: SessionLock,
        *,
        prompt_template: str = "Sir, {tool} requires approval. Proceed?",
        listen_timeout_seconds: float = 15.0,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._speaker = speaker
        self._listener = listener
        self._lock = session_lock
        self._prompt_template = prompt_template
        self._listen_timeout = listen_timeout_seconds
        self._now = now or datetime.now

    def render_prompt(self, req: ApprovalRequest) -> str:
        return self._prompt_template.format(tool=req.tool_name, persona=req.persona_id)

    async def request(self, req: ApprovalRequest) -> ApprovalOutcome:
        # Session-lock gate: only the locked user can approve.
        if not self._lock.can_approve(req.user_id, self._now()):
            log.info(
                "voice approval refused: session not locked to user %r",
                req.user_id,
            )
            return ApprovalOutcome(
                approved=False,
                decision="denied",
                reason="session_not_locked",
            )

        prompt = self.render_prompt(req)
        await self._speaker(prompt, req.persona_id, None)
        try:
            transcript = await self._listener(self._listen_timeout)
        except TimeoutError:
            return ApprovalOutcome(
                approved=False, decision="timeout", reason="no_response"
            )

        verdict = parse_yes_no(transcript)
        if verdict == "approved":
            return ApprovalOutcome(
                approved=True, decision="approved", reason=transcript
            )
        if verdict == "denied":
            return ApprovalOutcome(approved=False, decision="denied", reason=transcript)
        return ApprovalOutcome(
            approved=False, decision="denied", reason=f"ambiguous: {transcript!r}"
        )


__all__ = ["VoiceApprovalChannel", "parse_yes_no"]
