"""Tests for ``newton.voice.playback`` — system-player shell-out helper.

Playback is mocked end-to-end: ``shutil.which`` returns canned paths
and ``subprocess.run`` is a stub. No audio is ever produced. We also
guard Strategy D — importing the module must not pull in torch or
sounddevice.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from newton.voice import playback as playback_mod
from newton.voice.playback import (
    DEFAULT_PLAYERS,
    PlaybackError,
    play_wav,
)

# ── helpers ──────────────────────────────────────────────────────────────


def _touch_wav(tmp_path: Path) -> Path:
    """Create an empty placeholder WAV — we never read it."""
    wav = tmp_path / "tone.wav"
    wav.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
    return wav


class _RunCapture:
    """Recording ``subprocess.run`` replacement.

    Default behaviour: return a successful CompletedProcess. The test
    can swap ``returncode`` / ``stderr`` or override the side effect
    to raise ``TimeoutExpired`` / ``FileNotFoundError``.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.returncode = 0
        self.stderr = b""
        self.side_effect: BaseException | None = None

    def __call__(self, argv, **kwargs):  # noqa: ANN001
        self.calls.append(list(argv))
        if self.side_effect is not None:
            raise self.side_effect
        return subprocess.CompletedProcess(
            args=argv, returncode=self.returncode, stdout=b"", stderr=self.stderr
        )


def _which_only(*allowed: str):
    """Build a ``shutil.which`` stub that only resolves the given binaries."""
    allow = set(allowed)

    def _which(cmd: str) -> str | None:
        return f"/usr/bin/{cmd}" if cmd in allow else None

    return _which


# ── discovery order ─────────────────────────────────────────────────────


def test_play_wav_prefers_paplay_when_available(tmp_path, monkeypatch):
    wav = _touch_wav(tmp_path)
    monkeypatch.setattr(
        playback_mod.shutil, "which", _which_only("paplay", "aplay", "ffplay", "play")
    )
    monkeypatch.delenv("NEWTON_AUDIO_PLAYER", raising=False)
    runner = _RunCapture()
    monkeypatch.setattr(playback_mod.subprocess, "run", runner)

    play_wav(wav)

    assert len(runner.calls) == 1
    argv = runner.calls[0]
    assert argv[0] == "/usr/bin/paplay"
    assert argv[-1] == str(wav)


def test_play_wav_falls_back_through_the_chain(tmp_path, monkeypatch):
    wav = _touch_wav(tmp_path)
    monkeypatch.delenv("NEWTON_AUDIO_PLAYER", raising=False)
    runner = _RunCapture()
    monkeypatch.setattr(playback_mod.subprocess, "run", runner)

    # Walk the chain: each call leaves one fewer candidate available.
    expected_order = [name for name, _ in DEFAULT_PLAYERS]
    for skip in range(len(expected_order)):
        available = expected_order[skip:]
        monkeypatch.setattr(playback_mod.shutil, "which", _which_only(*available))
        runner.calls.clear()
        play_wav(wav)
        assert runner.calls[0][0] == f"/usr/bin/{available[0]}"


def test_play_wav_raises_when_no_player_is_found(tmp_path, monkeypatch):
    wav = _touch_wav(tmp_path)
    monkeypatch.delenv("NEWTON_AUDIO_PLAYER", raising=False)
    monkeypatch.setattr(playback_mod.shutil, "which", lambda _cmd: None)
    monkeypatch.setattr(
        playback_mod.subprocess,
        "run",
        lambda *a, **kw: pytest.fail("subprocess.run must not be invoked"),
    )

    with pytest.raises(PlaybackError) as excinfo:
        play_wav(wav)
    msg = str(excinfo.value)
    assert "no audio player found" in msg
    # Every default candidate is named in the error so users know what to install.
    for name, _ in DEFAULT_PLAYERS:
        assert name in msg


# ── error wrapping ──────────────────────────────────────────────────────


def test_play_wav_wraps_non_zero_exit(tmp_path, monkeypatch):
    wav = _touch_wav(tmp_path)
    monkeypatch.setattr(playback_mod.shutil, "which", _which_only("paplay"))
    monkeypatch.delenv("NEWTON_AUDIO_PLAYER", raising=False)
    runner = _RunCapture()
    runner.returncode = 2
    runner.stderr = b"Connection refused"
    monkeypatch.setattr(playback_mod.subprocess, "run", runner)

    with pytest.raises(PlaybackError) as excinfo:
        play_wav(wav)
    msg = str(excinfo.value)
    assert "exited 2" in msg
    assert "Connection refused" in msg


def test_play_wav_wraps_timeout(tmp_path, monkeypatch):
    wav = _touch_wav(tmp_path)
    monkeypatch.setattr(playback_mod.shutil, "which", _which_only("paplay"))
    monkeypatch.delenv("NEWTON_AUDIO_PLAYER", raising=False)
    runner = _RunCapture()
    runner.side_effect = subprocess.TimeoutExpired(cmd="paplay", timeout=0.5)
    monkeypatch.setattr(playback_mod.subprocess, "run", runner)

    with pytest.raises(PlaybackError) as excinfo:
        play_wav(wav, timeout=0.5)
    assert "timed out" in str(excinfo.value)


def test_play_wav_missing_file_raises_filenotfound(tmp_path, monkeypatch):
    monkeypatch.setattr(
        playback_mod.subprocess,
        "run",
        lambda *a, **kw: pytest.fail("must not run without an existing file"),
    )
    with pytest.raises(FileNotFoundError):
        play_wav(tmp_path / "missing.wav")


# ── overrides ───────────────────────────────────────────────────────────


def test_play_wav_env_override_wins_over_defaults(tmp_path, monkeypatch):
    wav = _touch_wav(tmp_path)
    monkeypatch.setattr(
        playback_mod.shutil, "which", _which_only("paplay", "my-player")
    )
    monkeypatch.setenv("NEWTON_AUDIO_PLAYER", "my-player")
    runner = _RunCapture()
    monkeypatch.setattr(playback_mod.subprocess, "run", runner)

    play_wav(wav)

    argv = runner.calls[0]
    assert argv[0] == "/usr/bin/my-player"
    # Override skips the default-flag list — only [binary, wav].
    assert argv[1] == str(wav)


def test_play_wav_explicit_player_arg_wins_over_env(tmp_path, monkeypatch):
    wav = _touch_wav(tmp_path)
    monkeypatch.setenv("NEWTON_AUDIO_PLAYER", "from-env")
    monkeypatch.setattr(playback_mod.shutil, "which", _which_only("from-arg"))
    runner = _RunCapture()
    monkeypatch.setattr(playback_mod.subprocess, "run", runner)

    play_wav(wav, player="from-arg")

    assert runner.calls[0][0] == "/usr/bin/from-arg"


def test_play_wav_non_blocking_uses_popen(tmp_path, monkeypatch):
    wav = _touch_wav(tmp_path)
    monkeypatch.setattr(playback_mod.shutil, "which", _which_only("paplay"))
    monkeypatch.delenv("NEWTON_AUDIO_PLAYER", raising=False)
    monkeypatch.setattr(
        playback_mod.subprocess,
        "run",
        lambda *a, **kw: pytest.fail("blocking=False must not call subprocess.run"),
    )

    captured: list[list[str]] = []

    class _FakePopen:
        def __init__(self, argv):
            captured.append(list(argv))

    monkeypatch.setattr(playback_mod.subprocess, "Popen", _FakePopen)

    play_wav(wav, blocking=False)

    assert captured and captured[0][0] == "/usr/bin/paplay"


# ── Strategy D import guard ─────────────────────────────────────────────


def test_playback_import_pulls_no_heavy_deps():
    """``newton.voice.playback`` must stay torch/sounddevice-free."""
    # The module has already been imported at the top of this file, so its
    # transitive imports are already in sys.modules — assert they're absent.
    assert "torch" not in sys.modules
    assert "sounddevice" not in sys.modules
    # The module itself uses only the stdlib seams we monkeypatch above.
    assert playback_mod.shutil.__name__ == "shutil"
    assert playback_mod.subprocess.__name__ == "subprocess"
