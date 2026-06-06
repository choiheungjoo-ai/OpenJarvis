"""Step 2.4 — tests for the three builtin tools and their registration."""

from __future__ import annotations

import pytest

from newton.tools.base import ToolContext
from newton.tools.builtin import (
    EchoToFileTool,
    EchoTool,
    SystemInfoTool,
    register_builtins,
)
from newton.tools.builtin.echo import EchoArgs
from newton.tools.builtin.echo_to_file import EchoToFileArgs
from newton.tools.builtin.system_info import SystemInfoArgs
from newton.tools.registry import RiskLevel, ToolRegistry


def _ctx(tmp_path=None, **kw) -> ToolContext:
    base = {"user_id": "sir", "persona_id": "jarvis"}
    if tmp_path is not None:
        base["extra"] = {"data_dir": str(tmp_path)}
    base.update(kw)
    return ToolContext(**base)


# -- echo ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_echo_returns_text():
    tool = EchoTool()
    result = await tool.execute(EchoArgs(text="hello"), _ctx())
    assert result.status == "ok"
    assert result.data == {"text": "hello"}


def test_echo_risk_is_safe():
    assert EchoTool.risk is RiskLevel.SAFE


# -- system_info --------------------------------------------------------------


@pytest.mark.asyncio
async def test_system_info_default_all_sections():
    tool = SystemInfoTool()
    result = await tool.execute(SystemInfoArgs(), _ctx())
    assert result.status == "ok"
    for section in ("cpu", "memory", "disk", "battery", "network", "processes"):
        assert section in result.data


@pytest.mark.asyncio
async def test_system_info_subset():
    tool = SystemInfoTool()
    result = await tool.execute(SystemInfoArgs(sections=["cpu", "memory"]), _ctx())
    assert set(result.data.keys()) == {"cpu", "memory"}
    assert "percent" in result.data["cpu"]
    assert "total" in result.data["memory"]


@pytest.mark.asyncio
async def test_system_info_processes_respects_top_n():
    tool = SystemInfoTool()
    result = await tool.execute(
        SystemInfoArgs(sections=["processes"], top_n_processes=3), _ctx()
    )
    assert len(result.data["processes"]) <= 3
    for proc in result.data["processes"]:
        assert {"pid", "name", "memory_percent"} <= set(proc.keys())


def test_system_info_risk_is_read_local():
    assert SystemInfoTool.risk is RiskLevel.READ_LOCAL


# -- echo_to_file -------------------------------------------------------------


@pytest.mark.asyncio
async def test_echo_to_file_writes_inside_scratch(tmp_path):
    tool = EchoToFileTool()
    result = await tool.execute(
        EchoToFileArgs(relative_path="note.txt", text="hi"), _ctx(tmp_path)
    )
    assert result.status == "ok"
    written = tmp_path / "tool_scratch" / "note.txt"
    assert written.read_text(encoding="utf-8") == "hi"
    assert result.data["bytes_written"] == 2
    assert result.data["appended"] is False


@pytest.mark.asyncio
async def test_echo_to_file_creates_subdirs(tmp_path):
    tool = EchoToFileTool()
    result = await tool.execute(
        EchoToFileArgs(relative_path="a/b/c.txt", text="deep"), _ctx(tmp_path)
    )
    assert result.status == "ok"
    assert (tmp_path / "tool_scratch" / "a" / "b" / "c.txt").is_file()


@pytest.mark.asyncio
async def test_echo_to_file_append(tmp_path):
    tool = EchoToFileTool()
    ctx = _ctx(tmp_path)
    await tool.execute(EchoToFileArgs(relative_path="log.txt", text="a"), ctx)
    result = await tool.execute(
        EchoToFileArgs(relative_path="log.txt", text="b", append=True), ctx
    )
    assert result.status == "ok"
    assert result.data["appended"] is True
    assert (tmp_path / "tool_scratch" / "log.txt").read_text() == "ab"


@pytest.mark.asyncio
async def test_echo_to_file_rejects_parent_traversal(tmp_path):
    tool = EchoToFileTool()
    result = await tool.execute(
        EchoToFileArgs(relative_path="../escape.txt", text="x"), _ctx(tmp_path)
    )
    assert result.status == "denied"
    assert "escapes scratch" in result.error
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.asyncio
async def test_echo_to_file_rejects_absolute_path(tmp_path):
    tool = EchoToFileTool()
    result = await tool.execute(
        EchoToFileArgs(relative_path="/etc/passwd", text="x"), _ctx(tmp_path)
    )
    assert result.status == "denied"


@pytest.mark.asyncio
async def test_echo_to_file_rejects_deep_traversal(tmp_path):
    tool = EchoToFileTool()
    result = await tool.execute(
        EchoToFileArgs(relative_path="a/../../escape.txt", text="x"), _ctx(tmp_path)
    )
    assert result.status == "denied"


def test_echo_to_file_risk_is_write_local():
    assert EchoToFileTool.risk is RiskLevel.WRITE_LOCAL


# -- registration -------------------------------------------------------------


def test_register_builtins_registers_three():
    reg = ToolRegistry()
    register_builtins(reg)
    assert len(reg) == 3
    names = [t.name for t in reg.list()]
    assert names == ["echo", "system_info", "echo_to_file"]  # risk-sorted


@pytest.mark.asyncio
async def test_register_builtins_dispatch_end_to_end(tmp_path):
    reg = ToolRegistry()
    register_builtins(reg)
    result = await reg.dispatch("echo", {"text": "roundtrip"}, _ctx(tmp_path))
    assert result.status == "ok"
    assert result.data == {"text": "roundtrip"}
