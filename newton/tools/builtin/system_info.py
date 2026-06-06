"""system_info — read host telemetry. Risk 1 (READ_LOCAL).

Reports CPU, memory, disk, battery, network interfaces, and the top
processes by memory. Read-only; no mutation of the host.
"""

from __future__ import annotations

from typing import Any, Literal

import psutil
from pydantic import BaseModel, Field

from newton.tools.base import RiskLevel, Tool, ToolContext, ToolResult

_Section = Literal["cpu", "memory", "disk", "battery", "network", "processes"]
_ALL_SECTIONS: tuple[_Section, ...] = (
    "cpu",
    "memory",
    "disk",
    "battery",
    "network",
    "processes",
)


class SystemInfoArgs(BaseModel):
    sections: list[_Section] = Field(
        default_factory=lambda: list(_ALL_SECTIONS),
        description="Which sections to include. Defaults to all.",
    )
    top_n_processes: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Process count for the 'processes' section (by memory).",
    )


class SystemInfoReturns(BaseModel):
    cpu: dict[str, Any] | None = None
    memory: dict[str, Any] | None = None
    disk: dict[str, Any] | None = None
    battery: dict[str, Any] | None = None
    network: dict[str, Any] | None = None
    processes: list[dict[str, Any]] | None = None


def _cpu() -> dict[str, Any]:
    return {
        "percent": psutil.cpu_percent(interval=0.1),
        "count_logical": psutil.cpu_count(logical=True),
        "count_physical": psutil.cpu_count(logical=False),
    }


def _memory() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    return {
        "total": vm.total,
        "available": vm.available,
        "used": vm.used,
        "percent": vm.percent,
    }


def _disk() -> dict[str, Any]:
    du = psutil.disk_usage("/")
    return {
        "total": du.total,
        "used": du.used,
        "free": du.free,
        "percent": du.percent,
    }


def _battery() -> dict[str, Any]:
    fn = getattr(psutil, "sensors_battery", None)
    batt = fn() if fn else None
    if batt is None:
        return {"present": False}
    return {
        "present": True,
        "percent": batt.percent,
        "power_plugged": batt.power_plugged,
        "secs_left": (None if batt.secsleft < 0 else batt.secsleft),
    }


def _network() -> dict[str, Any]:
    """Interface names + address families only. No traffic-content inspection."""
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    interfaces: dict[str, Any] = {}
    for name, addr_list in addrs.items():
        interfaces[name] = {
            "addresses": [
                {"family": str(a.family), "address": a.address} for a in addr_list
            ],
            "is_up": (stats[name].isup if name in stats else None),
        }
    return {"interfaces": interfaces}


def _processes(top_n: int) -> list[dict[str, Any]]:
    procs: list[dict[str, Any]] = []
    for p in psutil.process_iter(["pid", "name", "memory_percent"]):
        try:
            info = p.info
            procs.append(
                {
                    "pid": info["pid"],
                    "name": info["name"],
                    "memory_percent": round(info["memory_percent"] or 0.0, 2),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs.sort(key=lambda d: d["memory_percent"], reverse=True)
    return procs[:top_n]


class SystemInfoTool(Tool):
    name = "system_info"
    description = (
        "Report host telemetry: CPU, memory, disk, battery, network "
        "interfaces, and top processes by memory. Read-only."
    )
    risk = RiskLevel.READ_LOCAL
    args_schema = SystemInfoArgs
    returns_schema = SystemInfoReturns

    async def execute(self, args: SystemInfoArgs, context: ToolContext) -> ToolResult:
        builders = {
            "cpu": _cpu,
            "memory": _memory,
            "disk": _disk,
            "battery": _battery,
            "network": _network,
            "processes": lambda: _processes(args.top_n_processes),
        }
        data: dict[str, Any] = {}
        for section in args.sections:
            try:
                data[section] = builders[section]()
            except Exception as exc:  # one bad section must not sink the rest
                data[section] = {"error": f"{type(exc).__name__}: {exc}"}
        return ToolResult(status="ok", data=data)
