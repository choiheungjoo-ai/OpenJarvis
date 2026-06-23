"""Stage-1 activation — clap OR wake word, both first-class.

The block-5 design holds two Stage-1 triggers equal:

    * a 2-clap pattern (config: ``stage1.clap``)
    * any wake word in ``stage1.wake.wake_words``

This module wraps both behind one ``feed(chunk)`` interface so the
rest of the voice stack doesn't case-split. ``Stage1Detector`` is
itself agnostic of which underlying engines are used — we pass in
the constructed ``WakeDetector`` and ``ClapDetector``. Tests inject
:class:`ScriptedWakeDetector` so they don't need openwakeword.

The detector reports an :class:`ActivationEvent` per chunk with the
kind (``"wake"`` / ``"clap"``) and, for wake events, the matched
word. The persona engine (block 3) maps a wake word to a persona.

Clap permission modes (block-5 §5.12)
-------------------------------------
Three config-driven modes gate clap activations:

    * ``clap_shared`` — emit clap events unchanged. Default.
    * ``clap_off``    — the clap branch is skipped; wake words still fire.
    * ``clap_sir_only`` — emit the clap event but tag it
      ``requires_voice_confirmation=True``. The session layer must call
      :meth:`Stage1Detector.confirm_clap` with the first utterance's
      audio path; the clap is honoured only if Voice-ID resolves to
      ``privileged_user_id`` (default ``sir``).

We chose the "tag + confirm hook" design over an in-line synchronous
Voice-ID inside ``feed`` because Voice-ID needs an utterance, not a
single chunk — the session layer is what knows when an utterance has
ended. Keeping the decision point as a method on the detector makes
it testable without mic / session runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from newton.voice.clap_detector import ClapDetector, ClapMatch
from newton.voice.wake import WakeDetector, WakeMatch

# Identify-callable signature, matching ``VoiceIdService.identify``.
# Kept as a plain callable so tests pass a stub without constructing
# a full service (and so the detector takes no DB dependency).
VoiceIdentifier = Callable[[str | Path], tuple[str | None, float]]


@dataclass(frozen=True, slots=True)
class ActivationEvent:
    """The result of one chunk going through Stage 1."""

    kind: str  # "wake" or "clap"
    chunk_index: int
    wake_word: str | None = None
    score: float | None = None
    # Only set for clap events under ``clap_sir_only``. The session
    # layer must call ``Stage1Detector.confirm_clap`` before treating
    # the activation as live.
    requires_voice_confirmation: bool = False

    @classmethod
    def from_wake(cls, chunk_index: int, match: WakeMatch) -> ActivationEvent:
        return cls(
            kind="wake",
            chunk_index=chunk_index,
            wake_word=match.wake_word,
            score=match.score,
        )

    @classmethod
    def from_clap(
        cls,
        chunk_index: int,
        match: ClapMatch,  # noqa: ARG003
        *,
        requires_voice_confirmation: bool = False,
    ) -> ActivationEvent:
        return cls(
            kind="clap",
            chunk_index=chunk_index,
            requires_voice_confirmation=requires_voice_confirmation,
        )


@dataclass
class Stage1Detector:
    """Run both detectors against each chunk; emit the first hit.

    Wake wins ties (it's a more specific signal than a clap).
    Both detectors keep their own counters; passing the chunk index
    explicitly here gives ``ActivationEvent`` a consistent index.

    ``mode`` carries the clap permission policy (see module docstring).
    ``voice_id`` is the identify-callable used by ``clap_sir_only``;
    leaving it ``None`` is fine for the other modes.
    """

    wake: WakeDetector | None
    clap: ClapDetector | None
    mode: str = "clap_shared"
    voice_id: VoiceIdentifier | None = None
    privileged_user_id: str = "sir"
    _counter: int = 0

    def reset(self) -> None:
        self._counter = 0
        if self.clap is not None:
            self.clap.reset()

    def feed(self, chunk: np.ndarray) -> ActivationEvent | None:
        idx = self._counter
        self._counter += 1

        if self.wake is not None:
            match = self.wake.detect_chunk(chunk)
            if match is not None:
                return ActivationEvent.from_wake(idx, match)

        if self.clap is not None and self.mode != "clap_off":
            cm = self.clap.detect_chunk(chunk)
            if cm is not None:
                return ActivationEvent.from_clap(
                    idx,
                    cm,
                    requires_voice_confirmation=(self.mode == "clap_sir_only"),
                )

        return None

    def confirm_clap(self, audio_path: str | Path) -> bool:
        """Voice-ID the utterance after a ``clap_sir_only`` clap.

        Returns ``True`` iff the speaker resolves to
        ``self.privileged_user_id``. Callers that get ``False`` should
        drop the provisional activation.
        """
        if self.voice_id is None:
            raise RuntimeError(
                "confirm_clap requires a voice_id callable (clap_sir_only)"
            )
        user_id, _score = self.voice_id(audio_path)
        return user_id == self.privileged_user_id


__all__ = ["ActivationEvent", "Stage1Detector", "VoiceIdentifier"]
