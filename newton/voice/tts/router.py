"""TTS router — picks engine + sample by persona + language.

The routing table lives in ``config/voice.yaml`` under ``tts.routes``.
The router:

    1. Finds the first matching ``(persona, language)`` route. ``any``
       in either field is a wildcard.
    2. Resolves the configured ``voice_reference`` against
       ``tts.voice_root`` (default ``data/voices``).
    3. Constructs (or returns the cached) engine instance via an
       injectable ``engine_factory`` callable.

Everything is config-driven — no hardcoded "persona X needs engine Y"
mapping in Python. New personas land by editing the YAML.

Engines are cached per ``engine_name`` for the lifetime of the router,
not per route — two routes pointing at ``qwen3_tts_jarvis`` share one
instance. Lazy-load semantics from the underlying adapter mean the
heavy model itself loads only on first ``synthesize``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from newton.voice.config import TTSConfig, TTSRouteConfig
from newton.voice.tts.base import TTS

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TTSRouteResolution:
    """One resolved route — the engine to call + the sample to pass it."""

    engine: TTS
    voice_reference: Path | None
    route: TTSRouteConfig


class TTSRoutingError(LookupError):
    """Raised when no route matches and no fallback is configured."""


def _matches(route: TTSRouteConfig, persona: str, language: str) -> bool:
    persona_ok = route.persona == persona or route.persona == "any"
    language_ok = route.language == language or route.language == "any"
    return persona_ok and language_ok


@dataclass
class TTSRouter:
    """Resolve and cache engines per ``(persona, language)``."""

    config: TTSConfig
    engine_factory: Callable[[str], TTS]
    # Optional override of the voice_root (tests use tmp_path).
    voice_root_override: Path | None = None
    _engine_cache: dict[str, TTS] = field(default_factory=dict)

    def find_route(self, persona: str, language: str) -> TTSRouteConfig:
        """Look up the matching route *without* constructing the engine.

        Useful for pre-flight checks (sample existence) that should fail
        loudly before the heavy lazy model load. Raises ``TTSRoutingError``
        when nothing matches.
        """
        for route in self.config.routes:
            if _matches(route, persona, language):
                return route
        raise TTSRoutingError(
            f"no TTS route for persona={persona!r} language={language!r}"
        )

    def resolve(self, persona: str, language: str) -> TTSRouteResolution:
        """Find the first matching route and return engine + sample path."""
        match = self.find_route(persona, language)

        engine = self._engine_cache.get(match.engine)
        if engine is None:
            log.info("constructing TTS engine %r for first use", match.engine)
            engine = self.engine_factory(match.engine)
            self._engine_cache[match.engine] = engine

        ref = (
            self._resolve_voice_reference(match.voice_reference)
            if match.voice_reference
            else None
        )
        return TTSRouteResolution(engine=engine, voice_reference=ref, route=match)

    def _resolve_voice_reference(self, relative: str) -> Path:
        root = self.voice_root_override or Path(self.config.voice_root)
        return root / relative

    @property
    def engine_count(self) -> int:
        """How many engines the router has instantiated so far."""
        return len(self._engine_cache)


def default_engine_factory(name: str) -> TTS:
    """Construct the engine identified by ``name``.

    Used by production. Tests pass their own factory so they don't
    actually load qwen-tts / chatterbox. The factory is the single
    place that knows about concrete engine classes; the router stays
    string-keyed.

    Two Qwen3-TTS flavours ship by default:

    * ``qwen3_tts_base`` — Base cloning model (any persona; needs
      ``voice_reference`` + ``ref_text`` per synthesize call).
    * ``qwen3_tts_jarvis`` — JARVIS fine-tuned model (``speaker="jarvis"``;
      no reference needed).
    """
    # Local imports keep the router import-light when only one
    # engine is needed.
    from newton.voice.tts.chatterbox import ChatterboxTTS  # noqa: PLC0415
    from newton.voice.tts.qwen3 import (  # noqa: PLC0415
        Qwen3TTS,
        default_jarvis_model_path,
    )

    if name == "qwen3_tts_base":
        return Qwen3TTS(name="qwen3_tts_base")
    if name == "qwen3_tts_jarvis":
        return Qwen3TTS(
            name="qwen3_tts_jarvis",
            speaker="jarvis",
            model_path=default_jarvis_model_path(),
        )
    if name == "chatterbox":
        return ChatterboxTTS()
    raise ValueError(f"unknown TTS engine: {name!r}")


__all__ = [
    "TTSRouteResolution",
    "TTSRouter",
    "TTSRoutingError",
    "default_engine_factory",
]
