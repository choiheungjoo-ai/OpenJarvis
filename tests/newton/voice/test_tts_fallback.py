"""Tests for newton.voice.tts.fallback — chain + logging + announcement throttle."""

from __future__ import annotations

import numpy as np
from sqlalchemy import select

from newton.db import get_session, init_db
from newton.models.persona import Persona
from newton.models.tts_fallback_log import TTSFallbackLog
from newton.voice.tts.base import TTS, TTSResult
from newton.voice.tts.fallback import FallbackChain


def _seed_persona(persona_id: str = "jarvis") -> None:
    with get_session() as s:
        if s.get(Persona, persona_id) is None:
            s.add(Persona(persona_id=persona_id, display_name="JARVIS"))


class _GoodTTS(TTS):
    name = "good"

    def __init__(self, name: str = "good") -> None:
        self.name = name

    def synthesize(self, text, *, language=None, voice_reference=None, ref_text=None):  # noqa: ARG002
        # 1 s of a tone — passes audio-validation.
        sr = 16000
        wave = (
            0.3 * np.sin(2 * np.pi * 440 * np.linspace(0, 1, sr, endpoint=False))
        ).astype(np.float32)
        return TTSResult(audio=wave, sample_rate=sr)


class _BadTTS(TTS):
    name = "bad"

    def __init__(
        self, name: str = "bad", exc: type[BaseException] = RuntimeError
    ) -> None:
        self.name = name
        self._exc = exc

    def synthesize(self, text, *, language=None, voice_reference=None, ref_text=None):  # noqa: ARG002
        raise self._exc(f"{self.name} broke")


class _SilenceTTS(TTS):
    name = "silence"

    def __init__(self, name: str = "silence") -> None:
        self.name = name

    def synthesize(self, text, *, language=None, voice_reference=None, ref_text=None):  # noqa: ARG002
        # 1 s of silence — fails the silence_ratio check.
        return TTSResult(audio=np.zeros(16000, dtype=np.float32), sample_rate=16000)


# ── happy path: primary succeeds ───────────────────────────────────────


def test_primary_succeeds_no_fallback(isolated_db):
    init_db()
    _seed_persona()
    primary = _GoodTTS(name="primary")
    chain = FallbackChain(
        engines=[primary],
        language="en",
        persona_id="jarvis",
        session_id="T1",
    )
    with get_session() as s:
        out = chain.synthesize("hello", s)
    assert out.engine_used == "primary"
    assert out.fallbacks == []
    assert out.announced is False
    with get_session() as s:
        rows = s.execute(select(TTSFallbackLog)).scalars().all()
    assert rows == []


# ── falls through one engine ───────────────────────────────────────────


def test_falls_through_one_failure(isolated_db):
    init_db()
    _seed_persona()
    chain = FallbackChain(
        engines=[_BadTTS(name="primary"), _GoodTTS(name="secondary")],
        language="ko",
        persona_id="jarvis",
        session_id="T1",
    )
    with get_session() as s:
        out = chain.synthesize("안녕", s)
    assert out.engine_used == "secondary"
    assert out.fallbacks == ["primary"]
    assert out.announced is True  # first fallback this session

    with get_session() as s:
        rows = s.execute(select(TTSFallbackLog)).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.session_id == "T1"
    assert row.persona_id == "jarvis"
    assert row.language == "ko"
    assert row.primary_engine == "primary"
    assert row.fallback_engine == "secondary"
    assert row.failure_reason == "RuntimeError"
    assert row.text_length == len("안녕")


# ── two failures → ends at text_only ──────────────────────────────────


def test_all_engines_fail_ends_at_text_only(isolated_db):
    init_db()
    _seed_persona()
    chain = FallbackChain(
        engines=[_BadTTS(name="primary"), _BadTTS(name="secondary")],
        language="ko",
        persona_id="jarvis",
        session_id="T1",
    )
    with get_session() as s:
        out = chain.synthesize("hello", s)
    assert out.engine_used == "text_only"
    assert out.fallbacks == ["primary", "secondary"]
    assert out.result.audio.size == 0
    # Two failures, two log rows.
    with get_session() as s:
        rows = s.execute(select(TTSFallbackLog)).scalars().all()
    assert len(rows) == 2


# ── silence-ratio validation ──────────────────────────────────────────


def test_silence_output_triggers_fallback(isolated_db):
    init_db()
    _seed_persona()
    chain = FallbackChain(
        engines=[_SilenceTTS(name="silent_primary"), _GoodTTS(name="secondary")],
        language="en",
        persona_id="jarvis",
        session_id="T1",
    )
    with get_session() as s:
        out = chain.synthesize("hi", s)
    assert out.engine_used == "secondary"
    assert out.fallbacks == ["silent_primary"]
    with get_session() as s:
        rows = s.execute(select(TTSFallbackLog)).scalars().all()
    assert "silence_ratio" in rows[0].failure_reason


# ── timeout ──────────────────────────────────────────────────────────


def test_timeout_triggers_fallback(isolated_db):
    init_db()
    _seed_persona()
    # Fake monotonic that jumps 11s on every call after the first.
    times = iter([0.0, 11.0, 11.0, 11.05])

    chain = FallbackChain(
        engines=[_GoodTTS(name="slow"), _GoodTTS(name="fast")],
        language="en",
        persona_id="jarvis",
        session_id="T1",
        timeout_seconds=10.0,
        monotonic=lambda: next(times),
    )
    with get_session() as s:
        out = chain.synthesize("hi", s)
    assert out.engine_used == "fast"
    assert out.fallbacks == ["slow"]
    with get_session() as s:
        rows = s.execute(select(TTSFallbackLog)).scalars().all()
    assert rows[0].failure_reason == "timeout"


# ── announcement throttling ──────────────────────────────────────────


def test_announcement_fires_once_per_session(isolated_db):
    init_db()
    _seed_persona()
    chain = FallbackChain(
        engines=[_BadTTS(name="primary"), _GoodTTS(name="secondary")],
        language="en",
        persona_id="jarvis",
        session_id="T1",
    )
    with get_session() as s:
        first = chain.synthesize("a", s)
        second = chain.synthesize("b", s)
    assert first.announced is True
    assert second.announced is False  # throttled
    # Both logged separately though.
    with get_session() as s:
        rows = s.execute(select(TTSFallbackLog)).scalars().all()
    assert len(rows) == 2


# ── log without db_session is a no-op ─────────────────────────────────


def test_log_skipped_when_session_is_none():
    chain = FallbackChain(
        engines=[_BadTTS(name="primary"), _GoodTTS(name="secondary")],
        language="en",
        persona_id="jarvis",
        session_id="T1",
    )
    # No init_db; passing None for db_session — must not raise.
    out = chain.synthesize("hi", None)
    assert out.engine_used == "secondary"


# ── empty engine list still ends at text_only ─────────────────────────


def test_empty_engine_list_goes_straight_to_text_only(isolated_db):
    init_db()
    _seed_persona()
    chain = FallbackChain(
        engines=[],
        language="en",
        persona_id="jarvis",
        session_id="T1",
    )
    with get_session() as s:
        out = chain.synthesize("hi", s)
    assert out.engine_used == "text_only"


# ── memory error / file not found also caught ─────────────────────────


def test_oserror_triggers_fallback(isolated_db):
    init_db()
    _seed_persona()
    chain = FallbackChain(
        engines=[
            _BadTTS(name="primary", exc=FileNotFoundError),
            _GoodTTS(name="secondary"),
        ],
        language="en",
        persona_id="jarvis",
        session_id="T1",
    )
    with get_session() as s:
        out = chain.synthesize("hi", s)
    assert out.engine_used == "secondary"
    with get_session() as s:
        rows = s.execute(select(TTSFallbackLog)).scalars().all()
    assert rows[0].failure_reason == "FileNotFoundError"


def test_memoryerror_triggers_fallback(isolated_db):
    init_db()
    _seed_persona()
    chain = FallbackChain(
        engines=[
            _BadTTS(name="primary", exc=MemoryError),
            _GoodTTS(name="secondary"),
        ],
        language="en",
        persona_id="jarvis",
        session_id="T1",
    )
    with get_session() as s:
        out = chain.synthesize("hi", s)
    assert out.engine_used == "secondary"
    with get_session() as s:
        rows = s.execute(select(TTSFallbackLog)).scalars().all()
    assert rows[0].failure_reason == "MemoryError"
