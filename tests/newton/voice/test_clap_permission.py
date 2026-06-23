"""Tests for the clap permission modes — block-5 §5.12.

Cover all three modes, the validation hook on ``ClapConfig.mode``,
and Strategy D (no torch imported by the touched modules).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from newton.db import get_session, init_db
from newton.models.user import User
from newton.voice.clap_detector import ClapDetector
from newton.voice.config import ClapConfig, VoiceIdConfig
from newton.voice.stage1 import ActivationEvent, Stage1Detector
from newton.voice.voice_id import FakeVoiceEncoderBackend, VoiceIdService
from newton.voice.wake import ScriptedWakeDetector, WakeMatch

# ── helpers ──────────────────────────────────────────────────────────────


def _silent() -> np.ndarray:
    return np.zeros(512, dtype=np.float32)


def _peak() -> np.ndarray:
    return np.full(512, 0.3, dtype=np.float32)


def _clap_pair() -> list[np.ndarray]:
    """A peak-silence-peak sequence the detector will treat as one clap."""
    return [_peak(), *([_silent()] * 4), _peak(), *([_silent()] * 5)]


def _make_clap() -> ClapDetector:
    return ClapDetector(
        config=ClapConfig(
            enabled=True, peak_threshold=0.15, min_gap_ms=90, max_gap_ms=500
        ),
        sample_rate=16000,
        chunk_samples=512,
    )


def _seed_user(user_id: str) -> None:
    with get_session() as s:
        if s.get(User, user_id) is None:
            s.add(User(user_id=user_id, display_name=user_id.title()))


def _write_wav(tmp_path: Path, name: str, payload: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(payload)
    return p


# ── config validation ────────────────────────────────────────────────────


def test_clap_config_rejects_unknown_mode():
    with pytest.raises(ValueError, match="mode must be one of"):
        ClapConfig(mode="clap_anyone")


def test_clap_config_default_mode_is_shared():
    assert ClapConfig().mode == "clap_shared"
    assert ClapConfig().privileged_user_id == "sir"


@pytest.mark.parametrize("mode", ["clap_shared", "clap_sir_only", "clap_off"])
def test_clap_config_accepts_each_documented_mode(mode):
    cfg = ClapConfig(mode=mode)
    assert cfg.mode == mode


# ── clap_shared (default) — behaviour unchanged ──────────────────────────


def test_clap_shared_emits_event_without_confirmation_flag():
    s1 = Stage1Detector(wake=None, clap=_make_clap(), mode="clap_shared")
    events: list[ActivationEvent] = []
    for c in _clap_pair():
        e = s1.feed(c)
        if e is not None:
            events.append(e)
    assert len(events) == 1
    assert events[0].kind == "clap"
    assert events[0].requires_voice_confirmation is False


def test_default_mode_matches_clap_shared_behaviour():
    """No ``mode`` kwarg → today's behaviour preserved."""
    s1 = Stage1Detector(wake=None, clap=_make_clap())
    events = [e for e in (s1.feed(c) for c in _clap_pair()) if e is not None]
    assert len(events) == 1
    assert events[0].kind == "clap"
    assert events[0].requires_voice_confirmation is False


# ── clap_off — clap silenced, wake still fires ───────────────────────────


def test_clap_off_suppresses_clap_event():
    s1 = Stage1Detector(wake=None, clap=_make_clap(), mode="clap_off")
    events = [e for e in (s1.feed(c) for c in _clap_pair()) if e is not None]
    assert events == []


def test_clap_off_still_emits_wake_event():
    wake = ScriptedWakeDetector(scripted={2: WakeMatch(wake_word="jarvis", score=0.9)})
    s1 = Stage1Detector(wake=wake, clap=_make_clap(), mode="clap_off")
    events = [e for e in (s1.feed(_silent()) for _ in range(5)) if e is not None]
    assert len(events) == 1
    assert events[0].kind == "wake"
    assert events[0].wake_word == "jarvis"


def test_clap_off_works_even_when_clap_detector_is_none():
    s1 = Stage1Detector(wake=None, clap=None, mode="clap_off")
    # No detectors to fire — nothing should happen.
    assert s1.feed(_silent()) is None


# ── clap_sir_only — provisional clap + Voice-ID confirmation ─────────────


def test_clap_sir_only_tags_event_for_confirmation():
    s1 = Stage1Detector(wake=None, clap=_make_clap(), mode="clap_sir_only")
    events = [e for e in (s1.feed(c) for c in _clap_pair()) if e is not None]
    assert len(events) == 1
    assert events[0].kind == "clap"
    assert events[0].requires_voice_confirmation is True


def test_clap_sir_only_confirms_when_voice_id_matches_sir(isolated_db, tmp_path):
    init_db()
    _seed_user("sir")

    cfg = VoiceIdConfig(backend="fake", threshold=0.75)
    sir_wav = _write_wav(tmp_path, "sir.wav", b"sir-voice-clip")

    with get_session() as s:
        VoiceIdService(s, FakeVoiceEncoderBackend(), cfg).register("sir", sir_wav)

    with get_session() as s:
        svc = VoiceIdService(s, FakeVoiceEncoderBackend(), cfg)
        s1 = Stage1Detector(
            wake=None,
            clap=_make_clap(),
            mode="clap_sir_only",
            voice_id=svc.identify,
            privileged_user_id="sir",
        )
        assert s1.confirm_clap(sir_wav) is True


def test_clap_sir_only_rejects_when_voice_id_matches_other_user(isolated_db, tmp_path):
    init_db()
    _seed_user("sir")
    _seed_user("gf")

    cfg = VoiceIdConfig(backend="fake", threshold=0.75)
    sir_wav = _write_wav(tmp_path, "sir.wav", b"sir-sample")
    gf_wav = _write_wav(tmp_path, "gf.wav", b"gf-sample")

    with get_session() as s:
        be = FakeVoiceEncoderBackend()
        VoiceIdService(s, be, cfg).register("sir", sir_wav)
        VoiceIdService(s, be, cfg).register("gf", gf_wav)

    with get_session() as s:
        svc = VoiceIdService(s, FakeVoiceEncoderBackend(), cfg)
        s1 = Stage1Detector(
            wake=None,
            clap=_make_clap(),
            mode="clap_sir_only",
            voice_id=svc.identify,
            privileged_user_id="sir",
        )
        # gf's clip identifies as gf, not sir → confirmation fails.
        assert s1.confirm_clap(gf_wav) is False


def test_clap_sir_only_rejects_below_threshold(isolated_db, tmp_path):
    init_db()
    _seed_user("sir")

    # Threshold so high the fake encoder's cross-clip cosine never qualifies.
    cfg = VoiceIdConfig(backend="fake", threshold=0.99)
    enrolled = _write_wav(tmp_path, "enroll.wav", b"sir-voice")
    probe = _write_wav(tmp_path, "probe.wav", b"someone-else")

    with get_session() as s:
        VoiceIdService(s, FakeVoiceEncoderBackend(), cfg).register("sir", enrolled)

    with get_session() as s:
        svc = VoiceIdService(s, FakeVoiceEncoderBackend(), cfg)
        s1 = Stage1Detector(
            wake=None,
            clap=_make_clap(),
            mode="clap_sir_only",
            voice_id=svc.identify,
            privileged_user_id="sir",
        )
        # ``identify`` returns (None, score<threshold); confirmation fails.
        assert s1.confirm_clap(probe) is False


def test_clap_sir_only_without_voice_id_raises_on_confirm():
    s1 = Stage1Detector(wake=None, clap=_make_clap(), mode="clap_sir_only")
    with pytest.raises(RuntimeError, match="voice_id callable"):
        s1.confirm_clap("/tmp/anything.wav")


# ── Strategy D — touched modules don't pull in torch ─────────────────────


def test_stage1_module_does_not_import_torch_or_resemblyzer():
    """Fresh subprocess imports stage1 (and config) and checks no torch."""
    script = textwrap.dedent(
        """
        import sys
        import newton.voice.stage1  # noqa: F401
        import newton.voice.config  # noqa: F401
        assert 'torch' not in sys.modules, sorted(
            m for m in sys.modules if m.startswith('torch')
        )
        assert 'resemblyzer' not in sys.modules
        """
    )
    subprocess.run([sys.executable, "-c", script], check=True)
