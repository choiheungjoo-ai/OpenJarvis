"""Tests for newton.proactive.monitors."""

from __future__ import annotations

import pytest

from newton.proactive.monitors import ALLOWED_METRIC_TYPES, Monitor
from newton.proactive.monitors.gpu import (
    GpuTempMonitor,
    GpuUtilMonitor,
    _reset_for_tests,
    gpu_monitors,
)
from newton.proactive.monitors.system import (
    BatteryMonitor,
    CpuMonitor,
    MemoryMonitor,
)

# ── Monitor ABC ─────────────────────────────────────────────────────────────


def test_monitor_subclass_rejects_invalid_metric_type():
    """A concrete subclass with an unlisted metric_type can't be defined."""

    with pytest.raises(TypeError, match="metric_type"):

        class BadMonitor(Monitor):
            name = "bad"
            metric_type = "disk"  # not in ALLOWED_METRIC_TYPES

            def sample(self) -> float | None:
                return 0.0


def test_monitor_subclass_requires_name():
    """A concrete subclass must define a non-empty name."""

    with pytest.raises(TypeError, match="name"):

        class NamelessMonitor(Monitor):
            name = ""
            metric_type = "cpu"

            def sample(self) -> float | None:
                return 0.0


def test_allowed_metric_types_matches_schema():
    """The whitelist matches migration 001's CHECK constraint exactly."""

    assert ALLOWED_METRIC_TYPES == {
        "cpu",
        "gpu",
        "memory",
        "battery",
        "temperature",
        "network",
    }


# ── psutil monitors ─────────────────────────────────────────────────────────


def test_cpu_monitor_returns_percentage():
    m = CpuMonitor()
    v = m.sample()
    assert v is not None
    assert isinstance(v, float)
    assert 0.0 <= v <= 100.0


def test_memory_monitor_returns_percentage():
    m = MemoryMonitor()
    v = m.sample()
    assert v is not None
    assert isinstance(v, float)
    assert 0.0 <= v <= 100.0


def test_battery_monitor_handles_no_battery(monkeypatch):
    """``None`` from psutil → ``None`` from the monitor (no exception)."""

    import psutil

    monkeypatch.setattr(psutil, "sensors_battery", lambda: None)
    assert BatteryMonitor().sample() is None


def test_battery_monitor_handles_missing_attribute(monkeypatch):
    """Platforms where psutil has no sensors_battery: still returns None."""

    import psutil

    def _raise(*_a, **_kw):
        raise AttributeError("sensors_battery not implemented")

    monkeypatch.setattr(psutil, "sensors_battery", _raise)
    assert BatteryMonitor().sample() is None


def test_battery_monitor_returns_percent_when_available(monkeypatch):
    """When psutil reports a battery, the monitor surfaces the percent."""

    import psutil

    class _FakeBattery:
        percent = 73.5
        secsleft = 0
        power_plugged = False

    monkeypatch.setattr(psutil, "sensors_battery", lambda: _FakeBattery())
    assert BatteryMonitor().sample() == pytest.approx(73.5)


# ── GPU monitors (best-effort) ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_nvml_state():
    """Each GPU test gets a clean NVML init cache."""
    _reset_for_tests()
    yield
    _reset_for_tests()


def test_gpu_monitors_empty_when_pynvml_missing(monkeypatch):
    """No ``pynvml`` import → ``gpu_monitors()`` returns ``[]``."""

    import builtins

    real_import = builtins.__import__

    def _no_pynvml(name, *args, **kwargs):
        if name == "pynvml":
            raise ImportError("simulated: no pynvml")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_pynvml)
    assert gpu_monitors() == []


def test_gpu_util_returns_none_when_nvml_init_fails(monkeypatch):
    """If NVML init raises, samples are ``None`` and the daemon survives."""

    import builtins

    real_import = builtins.__import__

    def _broken_pynvml(name, *args, **kwargs):
        if name == "pynvml":
            raise ImportError("simulated: pynvml import fails")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _broken_pynvml)
    assert GpuUtilMonitor().sample() is None
    assert GpuTempMonitor().sample() is None
