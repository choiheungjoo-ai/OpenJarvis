"""NVIDIA GPU monitors (best-effort, optional).

Two monitors are exposed:

    GpuUtilMonitor  → metric_type='gpu'         (SM utilisation %)
    GpuTempMonitor  → metric_type='temperature' (°C)

Both go through ``pynvml`` (provided by the ``gpu-metrics`` extra:
``uv sync --extra gpu-metrics``). NVML talks to the NVIDIA kernel
module directly — it is **not** a CUDA dependency, so this code is
compatible with Newton's "no in-process CUDA" rule (strategy D).

Availability is best-effort:

    * If ``pynvml`` is not installed → :func:`gpu_monitors` returns
      ``[]`` and the daemon runs without GPU monitors.
    * If ``nvmlInit()`` raises (no driver, no device) → same outcome.
    * If a single per-sample call fails at runtime, the monitor returns
      ``None`` for that tick and the daemon skips the row; the next tick
      tries again.

Only device index 0 is sampled. Multi-GPU readout can be added later;
the schema has no device column today, so even if we sampled more we
could not distinguish the rows.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from newton.proactive.monitors import Monitor

log = logging.getLogger(__name__)

# Module-level NVML handle. We init once per process under a lock so the
# first call from any monitor primes the library; subsequent monitors
# reuse the same handle. ``None`` means "tried and failed" — we don't
# retry on every sample.
_NVML_LOCK = threading.Lock()
_NVML_READY: bool | None = None
_NVML_HANDLE: Any | None = None


def _try_init_nvml() -> Any | None:
    """Return a device-0 handle on success, ``None`` otherwise.

    Cached: a failed init is remembered for the rest of the process.
    """
    global _NVML_READY, _NVML_HANDLE

    with _NVML_LOCK:
        if _NVML_READY is not None:
            return _NVML_HANDLE
        try:
            import pynvml  # noqa: PLC0415  — lazy import is the whole point.

            pynvml.nvmlInit()
            _NVML_HANDLE = pynvml.nvmlDeviceGetHandleByIndex(0)
            _NVML_READY = True
            log.info("nvml: initialized on device 0")
            return _NVML_HANDLE
        except Exception as e:  # noqa: BLE001
            _NVML_READY = False
            _NVML_HANDLE = None
            log.info("nvml: unavailable (%s); GPU monitors disabled", e)
            return None


def _reset_for_tests() -> None:
    """Test hook — forget the cached init outcome.

    Production code never calls this; tests use it to flip pynvml
    availability between cases.
    """
    global _NVML_READY, _NVML_HANDLE
    with _NVML_LOCK:
        _NVML_READY = None
        _NVML_HANDLE = None


class GpuUtilMonitor(Monitor):
    """GPU SM utilisation as a percentage in [0.0, 100.0]."""

    name = "gpu_util"
    metric_type = "gpu"

    def sample(self) -> float | None:
        handle = _try_init_nvml()
        if handle is None:
            return None
        try:
            import pynvml  # noqa: PLC0415

            rates = pynvml.nvmlDeviceGetUtilizationRates(handle)
            return float(rates.gpu)
        except Exception as e:  # noqa: BLE001
            log.debug("gpu_util sample failed: %s", e)
            return None


class GpuTempMonitor(Monitor):
    """GPU core temperature in degrees Celsius."""

    name = "gpu_temp"
    metric_type = "temperature"

    def sample(self) -> float | None:
        handle = _try_init_nvml()
        if handle is None:
            return None
        try:
            import pynvml  # noqa: PLC0415

            # NVML_TEMPERATURE_GPU == 0; passing the literal avoids the
            # module-attribute lookup on every sample.
            return float(pynvml.nvmlDeviceGetTemperature(handle, 0))
        except Exception as e:  # noqa: BLE001
            log.debug("gpu_temp sample failed: %s", e)
            return None


def gpu_monitors() -> list[Monitor]:
    """Return GPU monitors if NVML can initialise, else an empty list.

    The probe is cached: a one-off init failure (no driver / no
    pynvml) means the daemon won't pay the import cost again.
    """
    if _try_init_nvml() is None:
        return []
    return [GpuUtilMonitor(), GpuTempMonitor()]


__all__ = ["GpuTempMonitor", "GpuUtilMonitor", "gpu_monitors"]
