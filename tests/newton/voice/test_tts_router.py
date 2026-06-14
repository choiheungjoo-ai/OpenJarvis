"""Tests for newton.voice.tts.router — config-driven routing + caching."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from newton.voice.config import TTSConfig, TTSRouteConfig
from newton.voice.tts.base import TTS, TTSResult
from newton.voice.tts.router import (
    TTSRouter,
    TTSRoutingError,
    default_engine_factory,
)


class _StubEngine(TTS):
    """A minimal TTS engine that records what it's asked to do."""

    # ``name`` is required at class level by the ABC; the constructor
    # overrides with a per-instance name so each stub can mimic a
    # different engine identity.
    name = "stub"

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[dict] = []

    def synthesize(self, text, *, language=None, voice_reference=None):
        self.calls.append(
            {"text": text, "language": language, "voice_reference": voice_reference}
        )
        return TTSResult(audio=np.zeros(1, dtype=np.float32), sample_rate=16000)


def _factory_factory():
    """Return ``(factory, registry)`` — factory caches into the registry."""

    registry: dict[str, _StubEngine] = {}

    def factory(name: str) -> TTS:
        if name not in registry:
            registry[name] = _StubEngine(name=name)
        return registry[name]

    return factory, registry


# ── basic routing ────────────────────────────────────────────────────────


def test_router_resolves_first_matching_route():
    cfg = TTSConfig(
        voice_root="data/voices",
        routes=[
            TTSRouteConfig(
                persona="jarvis",
                language="ko",
                engine="qwen3_tts_1.7b",
                voice_reference="jarvis/ko-001.wav",
            ),
        ],
    )
    factory, _ = _factory_factory()
    router = TTSRouter(config=cfg, engine_factory=factory)
    res = router.resolve("jarvis", "ko")
    assert res.route.engine == "qwen3_tts_1.7b"
    assert res.voice_reference == Path("data/voices/jarvis/ko-001.wav")
    assert res.engine.name == "qwen3_tts_1.7b"


def test_router_uses_voice_root_override(tmp_path):
    cfg = TTSConfig(
        voice_root="data/voices",
        routes=[
            TTSRouteConfig(
                persona="jarvis",
                language="ko",
                engine="qwen3_tts_1.7b",
                voice_reference="jarvis/ko-001.wav",
            ),
        ],
    )
    factory, _ = _factory_factory()
    router = TTSRouter(config=cfg, engine_factory=factory, voice_root_override=tmp_path)
    res = router.resolve("jarvis", "ko")
    assert res.voice_reference == tmp_path / "jarvis" / "ko-001.wav"


def test_router_wildcard_language_matches_any():
    cfg = TTSConfig(
        voice_root="data/voices",
        routes=[
            TTSRouteConfig(
                persona="butler",
                language="any",
                engine="qwen3_tts_0.6b",
                voice_reference="butler/ko-001.wav",
            ),
        ],
    )
    factory, _ = _factory_factory()
    router = TTSRouter(config=cfg, engine_factory=factory)
    res_ko = router.resolve("butler", "ko")
    res_en = router.resolve("butler", "en")
    assert res_ko.route.engine == "qwen3_tts_0.6b"
    assert res_en.route.engine == "qwen3_tts_0.6b"


def test_router_wildcard_persona_matches_any():
    cfg = TTSConfig(
        voice_root="data/voices",
        routes=[
            TTSRouteConfig(
                persona="any",
                language="ko",
                engine="qwen3_tts_0.6b",
                voice_reference=None,
            ),
        ],
    )
    factory, _ = _factory_factory()
    router = TTSRouter(config=cfg, engine_factory=factory)
    assert router.resolve("jarvis", "ko").route.engine == "qwen3_tts_0.6b"
    assert router.resolve("friday", "ko").route.engine == "qwen3_tts_0.6b"


# ── ordering precedence ──────────────────────────────────────────────────


def test_router_first_match_wins():
    """Two routes match — the earlier one in the list takes precedence."""

    cfg = TTSConfig(
        voice_root="data/voices",
        routes=[
            TTSRouteConfig(persona="jarvis", language="ko", engine="specific_first"),
            TTSRouteConfig(persona="any", language="any", engine="catchall"),
        ],
    )
    factory, _ = _factory_factory()
    router = TTSRouter(config=cfg, engine_factory=factory)
    assert router.resolve("jarvis", "ko").route.engine == "specific_first"
    # Mismatched persona but caught by the wildcard:
    assert router.resolve("nobody", "en").route.engine == "catchall"


# ── no match → raises ────────────────────────────────────────────────────


def test_router_raises_when_no_route_matches():
    cfg = TTSConfig(
        voice_root="data/voices",
        routes=[
            TTSRouteConfig(persona="butler", language="ko", engine="qwen3_tts_0.6b"),
        ],
    )
    factory, _ = _factory_factory()
    router = TTSRouter(config=cfg, engine_factory=factory)
    with pytest.raises(TTSRoutingError, match="no TTS route"):
        router.resolve("jarvis", "en")


def test_find_route_does_not_construct_engine():
    """find_route is the pre-flight: engine_factory must not be touched."""
    boom_calls = {"n": 0}

    def boom_factory(_name):
        boom_calls["n"] += 1
        raise AssertionError("factory must not run during find_route")

    cfg = TTSConfig(
        voice_root="data/voices",
        routes=[
            TTSRouteConfig(persona="jarvis", language="ko", engine="qwen3_tts_1.7b"),
        ],
    )
    router = TTSRouter(config=cfg, engine_factory=boom_factory)
    route = router.find_route("jarvis", "ko")
    assert route.engine == "qwen3_tts_1.7b"
    assert boom_calls["n"] == 0


def test_find_route_raises_on_no_match():
    cfg = TTSConfig(
        voice_root="data/voices",
        routes=[TTSRouteConfig(persona="butler", language="ko", engine="x")],
    )
    factory, _ = _factory_factory()
    router = TTSRouter(config=cfg, engine_factory=factory)
    with pytest.raises(TTSRoutingError, match="no TTS route"):
        router.find_route("jarvis", "en")


# ── engine caching ───────────────────────────────────────────────────────


def test_router_caches_engine_per_name():
    """Two routes that map to the same engine name share one instance."""

    cfg = TTSConfig(
        voice_root="data/voices",
        routes=[
            TTSRouteConfig(persona="jarvis", language="ko", engine="qwen3_tts_1.7b"),
            TTSRouteConfig(persona="friday", language="ko", engine="qwen3_tts_1.7b"),
        ],
    )
    factory, registry = _factory_factory()
    router = TTSRouter(config=cfg, engine_factory=factory)
    e1 = router.resolve("jarvis", "ko").engine
    e2 = router.resolve("friday", "ko").engine
    assert e1 is e2
    assert router.engine_count == 1
    assert len(registry) == 1


def test_router_constructs_separate_engines_for_distinct_names():
    cfg = TTSConfig(
        voice_root="data/voices",
        routes=[
            TTSRouteConfig(persona="butler", language="any", engine="qwen3_tts_0.6b"),
            TTSRouteConfig(persona="jarvis", language="ko", engine="qwen3_tts_1.7b"),
        ],
    )
    factory, _ = _factory_factory()
    router = TTSRouter(config=cfg, engine_factory=factory)
    e_butler = router.resolve("butler", "ko").engine
    e_jarvis = router.resolve("jarvis", "ko").engine
    assert e_butler is not e_jarvis
    assert router.engine_count == 2


# ── voice_reference can be None ──────────────────────────────────────────


def test_route_without_voice_reference_yields_none():
    cfg = TTSConfig(
        voice_root="data/voices",
        routes=[
            TTSRouteConfig(persona="any", language="any", engine="qwen3_tts_0.6b"),
        ],
    )
    factory, _ = _factory_factory()
    router = TTSRouter(config=cfg, engine_factory=factory)
    res = router.resolve("any", "any")
    assert res.voice_reference is None


# ── default_engine_factory honesty ──────────────────────────────────────


def test_default_factory_constructs_qwen3_engines():
    e_06 = default_engine_factory("qwen3_tts_0.6b")
    e_17 = default_engine_factory("qwen3_tts_1.7b")
    # The Qwen3TTS adapter sets name from model_size — confirm it.
    assert e_06.name == "qwen3_tts_0.6b"
    assert e_17.name == "qwen3_tts_1.7b"


def test_default_factory_constructs_chatterbox():
    """Step 5.6 wires Chatterbox; the factory now returns an instance."""
    e = default_engine_factory("chatterbox")
    assert e.name == "chatterbox"


def test_default_factory_rejects_unknown_name():
    with pytest.raises(ValueError, match="unknown TTS engine"):
        default_engine_factory("brand_x")


# ── end-to-end: router + factory + synthesize ───────────────────────────


def test_routed_synthesize_calls_engine_with_reference():
    cfg = TTSConfig(
        voice_root="data/voices",
        routes=[
            TTSRouteConfig(
                persona="jarvis",
                language="ko",
                engine="qwen3_tts_1.7b",
                voice_reference="jarvis/ko-001.wav",
            ),
        ],
    )
    factory, registry = _factory_factory()
    router = TTSRouter(config=cfg, engine_factory=factory)
    res = router.resolve("jarvis", "ko")
    res.engine.synthesize(
        "안녕하십니까", language="ko", voice_reference=res.voice_reference
    )
    stub: _StubEngine = registry["qwen3_tts_1.7b"]
    assert stub.calls == [
        {
            "text": "안녕하십니까",
            "language": "ko",
            "voice_reference": Path("data/voices/jarvis/ko-001.wav"),
        }
    ]
