"""Step 2.6 — tests for approval channels and the approval-enabled hook."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import newton.models  # noqa: F401  (populate metadata)
from newton.models.base import Base
from newton.models.tool_approval import ToolApproval
from newton.tools.approval import (
    ApprovalRequest,
    AutoApproveChannel,
    CLIApprovalChannel,
    DenyChannel,
)
from newton.tools.base import RiskLevel, Tool, ToolContext, ToolResult
from newton.tools.policy import build_policy_hook


class _Args(BaseModel):
    path: str = "x"


class _SafeTool(Tool):
    name = "safe_tool"
    description = "risk 0"
    risk = RiskLevel.SAFE
    args_schema = _Args
    returns_schema = _Args

    async def execute(self, args, context) -> ToolResult:
        return ToolResult(status="ok")


class _WriteTool(Tool):
    name = "write_tool"
    description = "risk 2"
    risk = RiskLevel.WRITE_LOCAL
    args_schema = _Args
    returns_schema = _Args

    async def execute(self, args, context) -> ToolResult:
        return ToolResult(status="ok")


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Maker = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def factory():
        s = Maker()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    return factory


def _ctx() -> ToolContext:
    return ToolContext(user_id="sir", persona_id="jarvis")


def _approval_count(factory) -> int:
    with factory() as s:
        return s.execute(select(func.count()).select_from(ToolApproval)).scalar_one()


# -- channels (unit) ----------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_channel_approves():
    out = await AutoApproveChannel().request(
        ApprovalRequest("t", 2, "jarvis", "sir", "args", "risk_default")
    )
    assert out.approved is True
    assert out.decision == "approved"


@pytest.mark.asyncio
async def test_deny_channel_denies():
    out = await DenyChannel().request(
        ApprovalRequest("t", 2, "jarvis", "sir", "args", "risk_default")
    )
    assert out.approved is False
    assert out.decision == "denied"


@pytest.mark.asyncio
async def test_cli_channel_accepts_yes():
    answers = iter(["y"])
    ch = CLIApprovalChannel(
        input_fn=lambda _p: next(answers), output_fn=lambda *_: None
    )
    out = await ch.request(ApprovalRequest("t", 2, "jarvis", "sir", "a", "db"))
    assert out.approved is True


@pytest.mark.asyncio
async def test_cli_channel_rejects_default():
    # Anything other than y/yes is a refusal (including empty input).
    for ans in ("", "n", "no", "nope", "  "):
        ch = CLIApprovalChannel(input_fn=lambda _p, a=ans: a, output_fn=lambda *_: None)
        out = await ch.request(ApprovalRequest("t", 2, "jarvis", "sir", "a", "db"))
        assert out.approved is False


# -- hook: no channel (safe default) ------------------------------------------


@pytest.mark.asyncio
async def test_hook_no_channel_denies_and_does_not_log(session_factory):
    hook = build_policy_hook(session_factory)  # no channel
    result = await hook(_WriteTool(), _Args(), _ctx())
    assert result.status == "needs_approval"
    assert _approval_count(session_factory) == 0  # nothing logged


# -- hook: safe tool never gated, never logged --------------------------------


@pytest.mark.asyncio
async def test_hook_safe_tool_allowed_and_unlogged(session_factory):
    hook = build_policy_hook(session_factory, approval_channel=DenyChannel())
    result = await hook(_SafeTool(), _Args(), _ctx())
    assert result is None  # allowed
    assert _approval_count(session_factory) == 0  # safe -> not an audit event


# -- hook: approve path -------------------------------------------------------


@pytest.mark.asyncio
async def test_hook_approve_allows_and_logs(session_factory):
    hook = build_policy_hook(session_factory, approval_channel=AutoApproveChannel())
    result = await hook(_WriteTool(), _Args(path="note.txt"), _ctx())
    assert result is None  # approved -> proceed
    assert _approval_count(session_factory) == 1
    with session_factory() as s:
        row = s.execute(select(ToolApproval)).scalar_one()
    assert row.decision == "approved"
    assert row.tool_name == "write_tool"
    assert row.risk_level == 2
    assert row.channel == "auto"
    assert row.policy_source == "risk_default"
    assert "note.txt" in row.args_summary


# -- hook: deny path ----------------------------------------------------------


@pytest.mark.asyncio
async def test_hook_deny_blocks_and_logs(session_factory):
    hook = build_policy_hook(session_factory, approval_channel=DenyChannel())
    result = await hook(_WriteTool(), _Args(), _ctx())
    assert result.status == "denied"
    assert _approval_count(session_factory) == 1
    with session_factory() as s:
        row = s.execute(select(ToolApproval)).scalar_one()
    assert row.decision == "denied"
    assert row.channel == "deny"


# -- hook: db relaxation skips approval entirely ------------------------------


@pytest.mark.asyncio
async def test_hook_db_relaxation_allows_without_logging(session_factory):
    from newton.models.tool_policy import ToolPolicy

    with session_factory() as s:
        s.add(ToolPolicy(tool_name="write_tool", require_approval=0))

    hook = build_policy_hook(session_factory, approval_channel=DenyChannel())
    result = await hook(_WriteTool(), _Args(), _ctx())
    assert result is None  # relaxed -> allowed, channel never consulted
    assert _approval_count(session_factory) == 0  # not gated -> not logged


# -- end-to-end through the registry ------------------------------------------


@pytest.mark.asyncio
async def test_registry_dispatch_with_approval(session_factory):
    from newton.tools.registry import ToolRegistry

    hook = build_policy_hook(session_factory, approval_channel=AutoApproveChannel())
    reg = ToolRegistry(policy_hook=hook)
    reg.register(_WriteTool())
    result = await reg.dispatch("write_tool", {"path": "f.txt"}, _ctx())
    assert result.status == "ok"  # approved then executed
    assert _approval_count(session_factory) == 1
