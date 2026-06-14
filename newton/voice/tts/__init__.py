"""Text-to-speech surface for the voice stack.

Two abstractions:

    :class:`TTS`  — ABC. ``synthesize(text, **kwargs) -> TTSResult``.
    :class:`TTSResult` — mono float32 + sample_rate.

Concrete engines lazy-load their models. Each persona + language
routes to one engine via the router (step 5.5). Fallbacks (step 5.13)
go through the same ABC.

Strategy D (voice): the ``import newton.voice.tts`` and even
``import newton.voice.tts.qwen3`` calls are safe without ``qwen-tts``
or torch installed — the heavy bits load on the first ``synthesize``.
"""

from newton.voice.tts.base import TTS, TTSResult, save_wav
from newton.voice.tts.qwen3 import Qwen3TTS
from newton.voice.tts.router import (
    TTSRouter,
    TTSRouteResolution,
    TTSRoutingError,
    default_engine_factory,
)

__all__ = [
    "TTS",
    "Qwen3TTS",
    "TTSResult",
    "TTSRouteResolution",
    "TTSRouter",
    "TTSRoutingError",
    "default_engine_factory",
    "save_wav",
]
