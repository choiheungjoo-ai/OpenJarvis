"""echo — the simplest tool. Risk 0 (SAFE): pure compute, no side effects."""

from __future__ import annotations

from pydantic import BaseModel, Field

from newton.tools.base import RiskLevel, Tool, ToolContext, ToolResult


class EchoArgs(BaseModel):
    text: str = Field(..., description="Text to echo back unchanged.")


class EchoReturns(BaseModel):
    text: str


class EchoTool(Tool):
    name = "echo"
    description = "Return the given text unchanged. Used for smoke-testing dispatch."
    risk = RiskLevel.SAFE
    args_schema = EchoArgs
    returns_schema = EchoReturns

    async def execute(self, args: EchoArgs, context: ToolContext) -> ToolResult:
        return ToolResult(status="ok", data={"text": args.text})
