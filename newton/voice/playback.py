"""WAV playback helper — stdlib only.

The mic side of the voice stack lazy-imports ``sounddevice`` for *input*
(see :mod:`newton.voice.audio_source`). Playback for the
``newton voice tts`` CLI doesn't need sounddevice or any other heavy
audio dep: shelling out to a system player is enough and keeps the
import graph free of torch / portaudio.

Player discovery is ordered: PulseAudio first (``paplay``, which works
out of the box on WSLg via ``PULSE_SERVER``), then ALSA (``aplay``),
then ffmpeg (``ffplay``), then sox (``play``). The first one
:func:`shutil.which` finds wins. Override with the ``NEWTON_AUDIO_PLAYER``
environment variable or the ``player`` arg — handy for non-WSL setups,
container playback, or piping into a custom script.

This module imports only ``os``, ``shutil``, ``subprocess`` from the
stdlib (plus ``pathlib`` for typing). No torch, no sounddevice, no
numpy.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

#: Players tried in order when no override is given. PulseAudio first
#: (WSLg's RDPSink speaks Pulse), then ALSA, then ffmpeg, then sox.
DEFAULT_PLAYERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("paplay", ()),
    ("aplay", ("-q",)),
    ("ffplay", ("-nodisp", "-autoexit", "-loglevel", "error")),
    ("play", ("-q",)),
)

_PLAYER_ENV_VAR = "NEWTON_AUDIO_PLAYER"


class PlaybackError(RuntimeError):
    """Raised when no usable player is found or the player exits non-zero."""


def _resolve_player(
    player: str | None,
) -> tuple[str, tuple[str, ...]]:
    """Pick the player binary + its default flags.

    Precedence: explicit ``player`` arg → ``NEWTON_AUDIO_PLAYER`` env →
    first entry of :data:`DEFAULT_PLAYERS` that :func:`shutil.which`
    can find. Overrides bypass the candidate list entirely (no extra
    flags are added — the user knows what they want).
    """
    override = player if player is not None else os.environ.get(_PLAYER_ENV_VAR)
    if override:
        resolved = shutil.which(override) or override
        return resolved, ()

    tried: list[str] = []
    for name, flags in DEFAULT_PLAYERS:
        path = shutil.which(name)
        if path is not None:
            return path, flags
        tried.append(name)
    raise PlaybackError(
        "no audio player found on PATH (tried: " + ", ".join(tried) + "). "
        f"Install one (e.g. `apt install pulseaudio-utils`) or set ${_PLAYER_ENV_VAR}."
    )


def play_wav(
    path: str | Path,
    *,
    blocking: bool = True,
    player: str | None = None,
    timeout: float | None = 60.0,
) -> None:
    """Play ``path`` through the first available system player.

    Parameters
    ----------
    path:
        WAV file to play. Must exist.
    blocking:
        If ``True`` (default), wait for the player to exit. If ``False``,
        spawn it and return immediately — useful for fire-and-forget UX
        but the caller is then responsible for the child process.
    player:
        Override the player binary (e.g. ``"paplay"``,
        ``"/usr/bin/aplay"``). Takes precedence over
        ``NEWTON_AUDIO_PLAYER``.
    timeout:
        Hard cap on blocking playback, in seconds. ``None`` waits
        forever. Ignored when ``blocking=False``.
    """
    wav_path = Path(path)
    if not wav_path.exists():
        raise FileNotFoundError(f"WAV not found: {wav_path}")

    binary, default_flags = _resolve_player(player)
    argv: list[str] = [binary, *default_flags, str(wav_path)]

    if not blocking:
        subprocess.Popen(argv)  # noqa: S603 — argv is a list, no shell
        return

    try:
        result = subprocess.run(  # noqa: S603 — argv is a list, no shell
            argv,
            check=False,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError as e:
        # which() said yes but exec disagreed (e.g. broken symlink).
        raise PlaybackError(f"player {binary!r} could not be executed: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise PlaybackError(
            f"player {binary!r} timed out after {timeout}s playing {wav_path}"
        ) from e

    if result.returncode != 0:
        stderr = (result.stderr or b"").decode("utf-8", "replace").strip()
        raise PlaybackError(
            f"player {binary!r} exited {result.returncode} playing {wav_path}"
            + (f": {stderr}" if stderr else "")
        )


__all__ = ["DEFAULT_PLAYERS", "PlaybackError", "play_wav"]
