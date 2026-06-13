"""PID file helpers for the proactive daemon.

The proactive daemon writes its PID to ``<data_dir>/newton-proactive.pid``
at startup and removes it on shutdown. ``newton proactive stop`` reads
the file, sends SIGTERM, and waits for the file to disappear; ``newton
proactive status`` reads the file to report whether the daemon is up.

Stale PID detection uses ``os.kill(pid, 0)``: signal 0 doesn't actually
deliver anything, it only validates that *some* process with that PID
exists. A surviving PID file whose process is gone is considered stale
and is overwritten / ignored.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PidStatus:
    """Result of inspecting a PID file."""

    pid: int | None
    running: bool
    stale: bool


def pidfile_path(data_dir: Path) -> Path:
    """Return the conventional location of the daemon's PID file."""
    return data_dir / "newton-proactive.pid"


def write_pidfile(path: Path, pid: int | None = None) -> None:
    """Write ``pid`` (default: this process) to ``path``.

    The parent directory must exist — the daemon will have created it
    via ``newton init`` long before this is called.
    """
    if pid is None:
        pid = os.getpid()
    path.write_text(f"{pid}\n", encoding="utf-8")


def read_pidfile(path: Path) -> int | None:
    """Return the PID stored in ``path``, or ``None`` if missing / garbage."""
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


def clear_pidfile(path: Path) -> None:
    """Best-effort removal of ``path``."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _process_alive(pid: int) -> bool:
    """True if a process with PID ``pid`` exists.

    Uses ``os.kill(pid, 0)`` — does not deliver a signal; only checks
    that the kernel still has a process table entry for that PID.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but isn't ours; from our perspective it's still
        # alive (we just can't signal it).
        return True
    return True


def inspect(path: Path) -> PidStatus:
    """Combine ``read_pidfile`` with a liveness check."""
    pid = read_pidfile(path)
    if pid is None:
        return PidStatus(pid=None, running=False, stale=False)
    alive = _process_alive(pid)
    return PidStatus(pid=pid, running=alive, stale=not alive)


__all__ = [
    "PidStatus",
    "clear_pidfile",
    "inspect",
    "pidfile_path",
    "read_pidfile",
    "write_pidfile",
]
