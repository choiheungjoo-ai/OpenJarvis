"""psutil-backed monitors: CPU, memory, battery.

All three are cheap and work CPU-only — no GPU, no CUDA, no torch.
``BatteryMonitor.sample()`` returns ``None`` on a desktop without a
battery (and on WSL2 hosts where psutil cannot read the host's battery),
which the daemon treats as "skip this row, keep the monitor".

Why no ``DiskMonitor``? The ``system_metrics.metric_type`` CHECK
constraint added in migration 001 allows
``cpu / gpu / memory / battery / temperature / network`` only. Disk is
not one of them. The block-4 design doc mentions disk in the bullet
list, but writing a 'disk' row would fail the CHECK. We deliberately
defer disk sampling until a later step adds a schema-widening migration
together with the threshold logic that will actually consume it.
"""

from __future__ import annotations

import psutil

from newton.proactive.monitors import Monitor


class CpuMonitor(Monitor):
    """System-wide CPU utilisation as a percentage in [0.0, 100.0].

    ``psutil.cpu_percent`` with no ``interval`` is non-blocking and
    returns the percentage seen *since the previous call*. The daemon
    primes the counter at startup so the first reported sample is real
    rather than the always-0.0 first call.
    """

    name = "cpu"
    metric_type = "cpu"

    def __init__(self) -> None:
        # Prime psutil's internal counter so the first sample isn't 0.0.
        psutil.cpu_percent(interval=None)

    def sample(self) -> float | None:
        return float(psutil.cpu_percent(interval=None))


class MemoryMonitor(Monitor):
    """Resident memory utilisation as a percentage in [0.0, 100.0]."""

    name = "memory"
    metric_type = "memory"

    def sample(self) -> float | None:
        return float(psutil.virtual_memory().percent)


class BatteryMonitor(Monitor):
    """Battery percentage in [0.0, 100.0], or ``None`` on AC-only hosts.

    On WSL2 ``psutil.sensors_battery()`` typically returns ``None`` (the
    host's battery is not exposed through ``/sys/class/power_supply``
    inside the VM). The daemon treats ``None`` as "no row to write",
    not as an error — laptops moving between AC and battery are
    expected.
    """

    name = "battery"
    metric_type = "battery"

    def sample(self) -> float | None:
        try:
            info = psutil.sensors_battery()
        except (AttributeError, NotImplementedError):
            # psutil exposes sensors_battery on Linux/Windows but not all
            # platforms; treat absence as "unavailable".
            return None
        if info is None:
            return None
        return float(info.percent)


__all__ = ["BatteryMonitor", "CpuMonitor", "MemoryMonitor"]
