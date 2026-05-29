"""Step 2.2 — tests for the tool base abstractions.

Scope: the shapes import, instantiate, serialize, and a minimal concrete
Tool runs through execute(). No registry/policy/approval yet.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from newton.tools import RiskLevel, Tool, ToolContext, ToolResult


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


# --- RiskLevel ---------------------------------------------------------------


def test_risk_levels_are_zero_through_four():
    assert [r.value for r in RiskLevel] == [0, 1, 2, 3, 4]


def test_risk_level_is_int_comparable():
    # IntEnum lets policy code compare by threshold.
    assert RiskLevel.SAFE < RiskLevel.WRITE_NETWORK
    assert RiskLevel.WRITE_LOCAL == 2


# --- ToolResult --------------------------------------------------------------


def test_tool_result_minimal_ok():
    r = ToolResult(status="ok", data={"text": "hi"})
    assert r.status == "ok"
    assert r.data == {"text": "hi"}
    assert r.error is None
    assert r.metadata == {}


def test_tool_result_serializes():
    r = ToolResult(status="needs_approval", metadata={"preview": {"path": "/tmp/x"}})
    dumped = r.model_dump()
    assert dumped["status"] == "needs_approval"
    assert dumped["metadata"]["preview"]["path"] == "/tmp/x"


def test_tool_result_rejects_unknown_status():
    with pytest.raises(ValueError):
        ToolResult(status="banana")


# --- ToolContext -------------------------------------------------------------


def test_tool_context_defaults():
    ctx = ToolContext(user_id="sir", persona_id="jarvis")
    assert ctx.session_id is None
    assert ctx.dry_run is False
    assert ctx.auto_approve is False
    assert ctx.extra == {}


def test_tool_context_extra_is_independent():
    a = ToolContext(user_id="sir", persona_id="jarvis")
    b = ToolContext(user_id="gf", persona_id="friday")
    a.extra["k"] = 1
    assert b.extra == {}  # no shared mutable default


# --- Tool --------------------------------------------------------------------


def test_tool_cannot_instantiate_abstract():
    with pytest.raises(TypeError):
        Tool()  # type: ignore[abstract]


def test_tool_args_model_validates():
    tool = _EchoTool()
    args = tool.args_model({"text": "hello"})
    assert isinstance(args, _EchoArgs)
    assert args.text == "hello"


def test_tool_args_model_rejects_bad_input():
    tool = _EchoTool()
    with pytest.raises(ValueError):
        tool.args_model({})  # missing required 'text'


@pytest.mark.asyncio
async def test_concrete_tool_executes():
    tool = _EchoTool()
    ctx = ToolContext(user_id="sir", persona_id="jarvis", auto_approve=True)
    result = await tool.execute(_EchoArgs(text="hi"), ctx)
    assert result.status == "ok"
    assert result.data == {"text": "hi"}


def test_tool_class_attributes_present():
    assert _EchoTool.name == "echo"
    assert _EchoTool.risk is RiskLevel.SAFE
    assert _EchoTool.args_schema is _EchoArgs
    assert _EchoTool.returns_schema is _EchoReturns
