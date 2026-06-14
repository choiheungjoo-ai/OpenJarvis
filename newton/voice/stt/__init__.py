"""Speech-to-text surface for the voice stack.

The :class:`STT` ABC keeps language-auto-detection + biasing
optional in the contract: every engine returns a
:class:`Transcription` carrying both the text and the detected
language; the optional ``initial_prompt`` kwarg lets step 5.8's
biasing dict slip in.

Concrete engines lazy-load their backends. faster-whisper uses
CTranslate2 (not torch), so it's the lightest of the model wrappers
in the voice stack — but it still loads weights, so we keep the
lazy contract.
"""

from newton.voice.stt.base import STT, Transcription
from newton.voice.stt.whisper import WhisperSTT

__all__ = ["STT", "Transcription", "WhisperSTT"]
