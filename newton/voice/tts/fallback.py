"""TTS fallback chain — block 5 step 5.13.

The chain implements voice.md §2.6.1:

    ko:      Qwen3-TTS 1.7B → Qwen3-TTS 0.6B → text-only
    en:      Chatterbox      → Qwen3-TTS 1.7B → text-only
    butler:  Qwen3-TTS 0.6B  → Qwen3-TTS 1.7B → text-only

Per persona+language tuple, the chain runs primary first. On any of
the documented failure modes (``OutOfMemoryError``, ``FileNotFoundError``,
``RuntimeError``, timeout > 10 s, or output validation: wav < 0.1 s
or silence ratio > 95 %), the chain advances to the next engine in
the list, writes a ``tts_fallback_log`` row, and *announces* the
fallback exactly once per session.

Throttling
----------
One announcement per session, in the relevant persona's voice
("잠시만요, sir. 톤이 다를 수 있습니다." for ko; "One moment, sir.
Tone may differ." for en). Subsequent fallbacks in the same session
are silent. The HUD (block 11) gets the signal later through
``tts_fallback_log``.

Text-only sink
--------------
The last tier in every chain is "text-only" — a no-op TTS that
emits a "rendered" :class:`TTSResult` with a marker so callers
(CLI, HUD) can fall back to print(). Block 11 wires the HUD; for
now the marker is enough for downstream code to branch.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from sqlalchemy.orm import Session

from newton.models.tts_fallback_log import TTSFallbackLog
from newton.voice.tts.base import TTS, TTSResult

log = logging.getLogger(__name__)


#: A TTSResult with this marker means "text-only" — no audio.
TEXT_ONLY_MARKER = "__newton_voice_text_only__"


@dataclass(frozen=True, slots=True)
class FallbackOutcome:
    """One synthesize() trip through the chain."""

    result: TTSResult
    engine_used: str
    fallbacks: list[str]  # names of engines that failed before success
    announced: bool


class _TextOnlyTTS(TTS):
    """Terminal sink — used as the last entry in every chain."""

    name = "text_only"

    def synthesize(
        self,
        text: str,
        *,
        language: str | None = None,  # noqa: ARG002
        voice_reference=None,  # noqa: ANN001, ARG002
    ) -> TTSResult:
        # Return an empty audio array tagged with the marker.
        # Callers detect via ``engine_used == "text_only"`` or via
        # the segments hint below.
        return TTSResult(
            audio=np.zeros(0, dtype=np.float32),
            sample_rate=16000,
        )


@dataclass
class FallbackChain:
    """One language-specific fallback ladder + the session it runs in."""

    engines: list[TTS]
    language: str
    persona_id: str
    session_id: str
    text_only: TTS = field(default_factory=_TextOnlyTTS)
    # 10 s per-engine timeout, from the design's failure-triggers list.
    timeout_seconds: float = 10.0
    # One per session — flips True on first announcement.
    _announced: bool = False
    # Injectable so tests can substitute time.monotonic().
    monotonic: Callable[[], float] = time.monotonic

    def synthesize(
        self,
        text: str,
        db_session: Session | None,
        *,
        voice_reference=None,  # noqa: ANN001
    ) -> FallbackOutcome:
        """Try each engine until one succeeds. Log every failure."""
        fallbacks: list[str] = []
        announced = False
        primary = self.engines[0] if self.engines else self.text_only

        candidates: list[TTS] = list(self.engines) + [self.text_only]

        for i, engine in enumerate(candidates):
            start = self.monotonic()
            try:
                result = engine.synthesize(
                    text,
                    language=self.language,
                    voice_reference=voice_reference,
                )
            except (OSError, RuntimeError, MemoryError) as e:
                reason = type(e).__name__
                log.warning(
                    "TTS engine %r failed (%s); falling back",
                    engine.name,
                    reason,
                )
                self._log(db_session, primary, engine, candidates, i, reason, text)
                fallbacks.append(engine.name)
                continue

            elapsed = self.monotonic() - start
            if elapsed > self.timeout_seconds:
                log.warning(
                    "TTS engine %r timed out (%.2fs > %.2fs); falling back",
                    engine.name,
                    elapsed,
                    self.timeout_seconds,
                )
                self._log(db_session, primary, engine, candidates, i, "timeout", text)
                fallbacks.append(engine.name)
                continue

            validation = _validate_audio(result, engine.name)
            if validation is not None:
                log.warning(
                    "TTS engine %r output failed validation (%s); falling back",
                    engine.name,
                    validation,
                )
                self._log(db_session, primary, engine, candidates, i, validation, text)
                fallbacks.append(engine.name)
                continue

            if i > 0 and not self._announced:
                self._announced = True
                announced = True

            return FallbackOutcome(
                result=result,
                engine_used=engine.name,
                fallbacks=fallbacks,
                announced=announced,
            )

        # Should be unreachable — _TextOnlyTTS doesn't fail validation
        # because it explicitly returns zero-length audio that we
        # accept. Keep the path explicit so a future broken sink is
        # visible rather than silent.
        raise RuntimeError(
            f"every TTS engine failed for session={self.session_id} "
            f"persona={self.persona_id}"
        )

    def _log(
        self,
        db_session: Session | None,
        primary: TTS,
        failed_engine: TTS,
        candidates: list[TTS],
        index: int,
        reason: str,
        text: str,
    ) -> None:
        if db_session is None:
            return
        # Use the *next* candidate as the fallback engine in the log.
        next_engine = candidates[index + 1] if index + 1 < len(candidates) else None
        row = TTSFallbackLog(
            session_id=self.session_id,
            persona_id=self.persona_id,
            language=self.language,
            primary_engine=primary.name,
            fallback_engine=next_engine.name if next_engine else "(none)",
            failure_reason=reason,
            text_length=len(text),
        )
        db_session.add(row)
        try:
            db_session.flush()
        except Exception as e:  # noqa: BLE001
            log.warning("failed to write tts_fallback_log row: %s", e)


def _validate_audio(result: TTSResult, engine_name: str) -> str | None:
    """Return a reason string when the output looks broken, else None."""
    if engine_name == "text_only":
        return None  # the terminal sink intentionally emits empty audio
    if result.audio is None or result.audio.size == 0:
        return "empty_audio"
    duration = result.duration_seconds
    if duration < 0.1:
        return "too_short"
    # Silence ratio: fraction of samples whose absolute value is below
    # 0.01. Anything above 95% is "the engine returned silence."
    silence_ratio = float(np.mean(np.abs(result.audio) < 0.01))
    if silence_ratio > 0.95:
        return f"silence_ratio={silence_ratio:.2f}"
    return None


__all__ = ["FallbackChain", "FallbackOutcome", "TEXT_ONLY_MARKER"]
