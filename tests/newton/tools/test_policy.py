"""Step 2.5 — tests for tool approval policy resolution.

Exercises the full decision order: exact > persona-wide > user-wide >
tool-wide > risk default. Uses a real in-memory SQLite engine with the
ToolPolicy table created from metadata.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Importing the models package registers every table on Base.metadata, so the
# ToolPolicy FK targets (users, personas) exist when create_all runs.
import newton.models  # noqa: F401
from newton.models.base import Base
from newton.models.tool_policy import ToolPolicy
from newton.tools.base import RiskLevel, Tool, ToolContext, ToolResult
from newton.tools.policy import (
    PolicyDecision,
    build_policy_hook,
    default_requires_approval,
    resolve_policy,
)

# -- minimal tools at two risk bands -----------------------------------------


class _Args(__import__("pydantic").BaseModel):
    pass


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


# -- in-memory DB fixture -----------------------------------------------------


@pytest.fixture
def session_factory():
    # Resolution logic is what's under test here, not FK integrity (db.py
    # owns FK enforcement and Block 1 covers it). This in-memory engine
    # deliberately leaves foreign_keys OFF so policy rows can reference
    # persona/user ids without seeding the full identity schema.
    engine = create_engine("sqlite:///:memory:", future=True)

    # Build the full schema so FK targets exist. Leave foreign_keys OFF
    # (no PRAGMA): this suite tests resolution, not FK integrity, so policy
    # rows may reference persona/user ids without seeding those tables.
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


def _ctx(persona="jarvis", user="sir") -> ToolContext:
    return ToolContext(user_id=user, persona_id=persona)


def _add(factory, **kw):
    with factory() as s:
        s.add(ToolPolicy(**kw))


# -- risk defaults (step 5) ---------------------------------------------------


def test_default_safe_no_approval():
    assert default_requires_approval(RiskLevel.SAFE) is False
    assert default_requires_approval(RiskLevel.READ_LOCAL) is False


def test_default_write_and_above_require_approval():
    assert default_requires_approval(RiskLevel.WRITE_LOCAL) is True
    assert default_requires_approval(RiskLevel.READ_NETWORK) is True
    assert default_requires_approval(RiskLevel.WRITE_NETWORK) is True


def test_resolve_falls_back_to_risk_default_when_no_rows(session_factory):
    with session_factory() as s:
        d = resolve_policy(s, _SafeTool(), _ctx())
    assert d == PolicyDecision(require_approval=False, source="risk_default")

    with session_factory() as s:
        d = resolve_policy(s, _WriteTool(), _ctx())
    assert d.require_approval is True
    assert d.source == "risk_default"


# -- cascade tiers ------------------------------------------------------------


def test_tool_wide_row_overrides_risk_default(session_factory):
    # write_tool would default to approval; a tool-wide row relaxes it.
    _add(session_factory, tool_name="write_tool", require_approval=0)
    with session_factory() as s:
        d = resolve_policy(s, _WriteTool(), _ctx())
    assert d.require_approval is False
    assert d.source == "db"


def test_user_wide_beats_tool_wide(session_factory):
    _add(session_factory, tool_name="write_tool", require_approval=0)  # tier 4
    _add(
        session_factory,
        tool_name="write_tool",
        user_id="sir",
        require_approval=1,
    )  # tier 3
    with session_factory() as s:
        d = resolve_policy(s, _WriteTool(), _ctx(user="sir"))
    assert d.require_approval is True  # user-wide wins


def test_persona_wide_beats_user_wide(session_factory):
    _add(
        session_factory,
        tool_name="write_tool",
        user_id="sir",
        require_approval=1,
    )  # tier 3
    _add(
        session_factory,
        tool_name="write_tool",
        persona_id="jarvis",
        require_approval=0,
    )  # tier 2
    with session_factory() as s:
        d = resolve_policy(s, _WriteTool(), _ctx(persona="jarvis", user="sir"))
    assert d.require_approval is False  # persona-wide wins


def test_exact_beats_everything(session_factory):
    _add(session_factory, tool_name="write_tool", require_approval=1)  # tier 4
    _add(
        session_factory,
        tool_name="write_tool",
        persona_id="jarvis",
        require_approval=1,
    )  # tier 2
    _add(
        session_factory,
        tool_name="write_tool",
        persona_id="jarvis",
        user_id="sir",
        require_approval=0,
    )  # tier 1
    with session_factory() as s:
        d = resolve_policy(s, _WriteTool(), _ctx(persona="jarvis", user="sir"))
    assert d.require_approval is False  # exact wins
    assert d.source == "db"


def test_non_matching_rows_are_ignored(session_factory):
    # Rows for other persona/user must not apply.
    _add(
        session_factory,
        tool_name="write_tool",
        persona_id="friday",
        require_approval=0,
    )
    _add(
        session_factory,
        tool_name="write_tool",
        user_id="gf",
        require_approval=0,
    )
    with session_factory() as s:
        d = resolve_policy(s, _WriteTool(), _ctx(persona="jarvis", user="sir"))
    # Neither row matches -> risk default (approval for write).
    assert d.require_approval is True
    assert d.source == "risk_default"


def test_row_for_other_tool_ignored(session_factory):
    _add(session_factory, tool_name="some_other_tool", require_approval=0)
    with session_factory() as s:
        d = resolve_policy(s, _WriteTool(), _ctx())
    assert d.source == "risk_default"


# -- hook ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hook_denies_when_approval_required(session_factory):
    hook = build_policy_hook(session_factory)
    result = await hook(_WriteTool(), _Args(), _ctx())
    assert result is not None
    assert result.status == "needs_approval"
    assert result.metadata["policy_source"] == "risk_default"


@pytest.mark.asyncio
async def test_hook_allows_when_no_approval_required(session_factory):
    hook = build_policy_hook(session_factory)
    result = await hook(_SafeTool(), _Args(), _ctx())
    assert result is None  # allowed


@pytest.mark.asyncio
async def test_hook_respects_db_relaxation(session_factory):
    _add(session_factory, tool_name="write_tool", require_approval=0)
    hook = build_policy_hook(session_factory)
    result = await hook(_WriteTool(), _Args(), _ctx())
    assert result is None  # DB row relaxed it -> allowed
