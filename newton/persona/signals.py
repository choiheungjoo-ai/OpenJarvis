"""Stage-2 activation signals for persona routing.

Newton activates a persona in two stages. Stage 1 (identity: who is speaking)
is block 5/6 territory. Stage 2 is the *intent* signal that selects which
persona to run, and comes in two forms:

  - VoiceNamingSignal: the speaker named a persona out loud ("JARVIS").
  - FaceBindingSignal: identity was established by face with no explicit
    naming, so the user's default persona applies.

Block 3 only models these as data and routes on them; the actual sensors
(wake-word, face recognition) arrive in later blocks.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceNamingSignal:
    """The speaker explicitly named a persona (e.g. a wake word)."""

    persona_name: str


@dataclass(frozen=True)
class FaceBindingSignal:
    """Identity established without naming; use the user's default persona."""


# A Stage-2 signal is one of the above.
Stage2Signal = VoiceNamingSignal | FaceBindingSignal


__all__ = ["FaceBindingSignal", "Stage2Signal", "VoiceNamingSignal"]
