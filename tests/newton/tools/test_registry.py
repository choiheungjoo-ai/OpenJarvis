"""Step 2.3 — tests for ToolRegistry and dispatch.

Covers registration (duplicate, unknown), list ordering by risk, and every
dispatch path: arg validation failure, policy-hook deny / needs_approval,
dry-run short-circuit, normal execution, and the no-hook allow default.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from newton.tools.base import RiskLevel, Tool, ToolContext, ToolResult
from newton.tools.registry import PolicyHook, ToolError, ToolRegistry


class _EchoArgs(BaseModel):
    text: str


class _EchoReturns(BaseModel):
    text: str


class _EchoTool(Tool):
    name = "echo"
    description = "Return the text unchanged."
    risk = RiskLevel.SAFE
    args_schema = _EchoArgs
    returns_schema = _EchoReturns

    async def execute(self, args: _EchoArgs, context: ToolContext) -> ToolResult:
        return ToolResult(status="ok", data={"text": args.text})


class _WriteArgs(BaseModel):
    path: str


class _WriteTool(Tool):
    name = "echo_to_file"
    description = "Pretend to write a file."
    risk = RiskLevel.WRITE_LOCAL
    args_schema = _WriteArgs
    returns_schema = _EchoReturns

    async def execute(self, args: _WriteArgs, context: ToolContext) -> ToolResult:
        return ToolResult(status="ok", data={"path": args.path})


def _ctx(**kw) -> ToolContext:
    base = {"user_id": "sir", "persona_id": "jarvis"}
    base.update(kw)
    return ToolContext(**base)


# -- registration -------------------------------------------------------------


def test_register_and_get():
    reg = ToolRegistry()
    tool = _EchoTool()
    reg.register(tool)
    assert reg.get("echo") is tool
    assert "echo" in reg
    assert len(reg) == 1


def test_duplicate_registration_raises():
    reg = ToolRegistry()
    reg.register(_EchoTool())
    with pytest.raises(ToolError, match="already registered"):
        reg.register(_EchoTool())


def test_unknown_tool_raises():
    reg = ToolRegistry()
    with pytest.raises(ToolError, match="unknown tool"):
        reg.get("nope")


def test_list_sorted_by_risk_then_name():
    reg = ToolRegistry()
    reg.register(_WriteTool())  # risk 2
    reg.register(_EchoTool())  # risk 0
    names = [t.name for t in reg.list()]
    assert names == ["echo", "echo_to_file"]  # safest first


# -- dispatch: validation -----------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_invalid_args_returns_error():
    reg = ToolRegistry()
    reg.register(_EchoTool())
    result = await reg.dispatch("echo", {}, _ctx())
    assert result.status == "error"
    assert "invalid args" in result.error
    assert result.metadata["validation_errors"]


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_raises():
    reg = ToolRegistry()
    with pytest.raises(ToolError):
        await reg.dispatch("ghost", {}, _ctx())


# -- dispatch: no hook (default allow) ----------------------------------------


@pytest.mark.asyncio
async def test_dispatch_without_hook_executes():
    reg = ToolRegistry()
    reg.register(_EchoTool())
    result = await reg.dispatch("echo", {"text": "hi"}, _ctx())
    assert result.status == "ok"
    assert result.data == {"text": "hi"}


# -- dispatch: policy hook (Step 2.6 seam) ------------------------------------


@pytest.mark.asyncio
async def test_policy_hook_can_deny():
    async def deny_hook(tool, args, context) -> ToolResult | None:
        return ToolResult(status="denied", error="policy refused")

    reg = ToolRegistry(policy_hook=deny_hook)
    reg.register(_EchoTool())
    result = await reg.dispatch("echo", {"text": "hi"}, _ctx())
    assert result.status == "denied"
    assert result.error == "policy refused"


@pytest.mark.asyncio
async def test_policy_hook_can_request_approval():
    async def approval_hook(tool, args, context) -> ToolResult | None:
        return ToolResult(status="needs_approval", metadata={"asked": True})

    reg = ToolRegistry(policy_hook=approval_hook)
    reg.register(_WriteTool())
    result = await reg.dispatch("echo_to_file", {"path": "/tmp/x"}, _ctx())
    assert result.status == "needs_approval"
    assert result.metadata["asked"] is True


@pytest.mark.asyncio
async def test_policy_hook_returning_none_allows_execution():
    async def passthrough(tool, args, context) -> ToolResult | None:
        return None

    reg = ToolRegistry(policy_hook=passthrough)
    reg.register(_EchoTool())
    result = await reg.dispatch("echo", {"text": "ok"}, _ctx())
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_auto_approve_bypasses_hook():
    calls = {"n": 0}

    async def counting_hook(tool, args, context) -> ToolResult | None:
        calls["n"] += 1
        return ToolResult(status="denied")

    reg = ToolRegistry(policy_hook=counting_hook)
    reg.register(_EchoTool())
    result = await reg.dispatch("echo", {"text": "hi"}, _ctx(auto_approve=True))
    assert result.status == "ok"
    assert calls["n"] == 0  # hook never consulted under auto_approve


# -- dispatch: dry-run --------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_does_not_execute():
    class _Boom(Tool):
        name = "boom"
        description = "Must never run in dry-run."
        risk = RiskLevel.WRITE_LOCAL
        args_schema = _WriteArgs
        returns_schema = _EchoReturns

        async def execute(self, args, context) -> ToolResult:
            raise AssertionError("execute must not be called in dry-run")

    reg = ToolRegistry()
    reg.register(_Boom())
    result = await reg.dispatch("boom", {"path": "/tmp/x"}, _ctx(dry_run=True))
    assert result.status == "needs_approval"
    assert result.metadata["dry_run"] is True
    assert result.metadata["tool"] == "boom"
    assert result.metadata["risk"] == 2
    assert result.metadata["args"] == {"path": "/tmp/x"}


# -- protocol -----------------------------------------------------------------


def test_policy_hook_is_runtime_checkable():
    async def hook(tool, args, context):
        return None

    assert isinstance(hook, PolicyHook)
