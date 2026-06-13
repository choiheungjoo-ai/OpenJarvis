"""Monitor abstraction and registry.

A ``Monitor`` declares the ``metric_type`` it writes (one of the six
values the ``system_metrics.metric_type`` CHECK constraint allows) and
returns a single floating-point sample from :meth:`sample`. Returning
``None`` means the signal is unavailable on this host (no battery,
no GPU, sensor not exposed) — the daemon skips writing a row, but
keeps the monitor in the loop because availability can change at
runtime (laptop unplugged, GPU hot-plugged in a container, …).

The daemon iterates a list of monitors. Adding a new signal in a later
step is "drop in a Monitor subclass, append it to the default list" —
no metric-specific code path lives in the daemon itself.

Why no ``disk`` monitor here? The ``system_metrics.metric_type`` CHECK
constraint allows ``cpu / gpu / memory / battery / temperature /
network`` only. Sampling disk would require widening the CHECK via a
new migration, which is out of scope for step 4.1 — defer until a
caller actually needs disk telemetry.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

# ─────────────────────────────────────────────────────────────────────────────
# Allowed metric_type values (mirrors migration 001's CHECK constraint).
# Importing code uses this set to validate a Monitor at construction time
# rather than discovering the mismatch only when SQLite refuses the row.
# ─────────────────────────────────────────────────────────────────────────────

ALLOWED_METRIC_TYPES: frozenset[str] = frozenset(
    {"cpu", "gpu", "memory", "battery", "temperature", "network"}
)


class Monitor(ABC):
    """One source of one ``system_metrics`` row per sample.

    Subclasses set the ``name`` and ``metric_type`` class attributes and
    implement :meth:`sample`. ``name`` is the human-readable identifier
    used in logs and ``proactive status`` output; ``metric_type`` is the
    DB enum value.
    """

    name: str
    metric_type: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Abstract subclasses (no concrete name/metric_type yet) skip
        # validation. Concrete subclasses must pin both.
        if getattr(cls, "__abstractmethods__", None):
            return
        if not getattr(cls, "name", None):
            raise TypeError(f"{cls.__name__}: Monitor subclass must define 'name'")
        mt = getattr(cls, "metric_type", None)
        if mt not in ALLOWED_METRIC_TYPES:
            allowed = sorted(ALLOWED_METRIC_TYPES)
            raise TypeError(f"{cls.__name__}: metric_type {mt!r} not in {allowed}")

    @abstractmethod
    def sample(self) -> float | None:
        """Return the current value, or ``None`` if unavailable."""


def default_monitors() -> list[Monitor]:
    """Return the standard monitor set: psutil signals + best-effort GPU.

    A GPU monitor that can't initialize (no NVIDIA driver, no pynvml in
    the env) is silently absent; psutil monitors always succeed.
    """
    # Imported lazily to avoid pulling pynvml into module-import time for
    # GPU-less hosts. The GPU module's helper returns an empty list when
    # pynvml is missing or NVML init fails.
    from newton.proactive.monitors.gpu import gpu_monitors
    from newton.proactive.monitors.system import (
        BatteryMonitor,
        CpuMonitor,
        MemoryMonitor,
    )

    monitors: list[Monitor] = [CpuMonitor(), MemoryMonitor(), BatteryMonitor()]
    monitors.extend(gpu_monitors())
    return monitors


__all__ = ["ALLOWED_METRIC_TYPES", "Monitor", "default_monitors"]
