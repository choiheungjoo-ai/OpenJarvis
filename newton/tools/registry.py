"""Newton tool registry and dispatch.

Step 2.3 — central registry Newton owns (Step 2.1 confirmed OpenJarvis has
no central ToolRegistry to register into). ``dispatch`` is the seam where
the approval hook lands in Step 2.6.

Path C: ``dispatch`` takes an optional ``PolicyHook``. When none is given it
allows every call (current behaviour). Step 2.6 injects a real hook WITHOUT
reopening ``dispatch`` itself — consistent with the block-2 locked decision
that the approval layer is fully pluggable.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import ValidationError

from newton.tools.base import RiskLevel, Tool, ToolContext, ToolResult


class ToolError(Exception):
    """Registry-level error (duplicate name, unknown tool, bad args)."""


@runtime_checkable
class PolicyHook(Protocol):
    """Decides what happens to a call before it executes.

    Implemented for real in Step 2.6 (policy matrix + approval channel).
    Returns a verdict ToolResult for the non-ok paths, or ``None`` to allow
    execution to proceed.
    """

    async def __call__(
        self, tool: Tool, args: object, context: ToolContext
    ) -> ToolResult | None: ...


class ToolRegistry:
    """Holds tools and dispatches calls through them."""

    def __init__(self, policy_hook: PolicyHook | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        self._policy_hook = policy_hook

    # -- registration ---------------------------------------------------------

    def register(self, tool: Tool) -> None:
        """Register a tool instance. Duplicate names raise ``ToolError``."""
        name = tool.name
        if name in self._tools:
            raise ToolError(f"tool already registered: {name!r}")
        self._tools[name] = tool

    def get(self, name: str) -> Tool:
        """Return a registered tool or raise ``ToolError``."""
        try:
            return self._tools[name]
        except KeyError:
            raise ToolError(f"unknown tool: {name!r}") from None

    def list(self) -> list[Tool]:
        """All tools, sorted by (risk, name) — safest first, stable."""
        return sorted(self._tools.values(), key=lambda t: (RiskLevel(t.risk), t.name))

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    # -- dispatch -------------------------------------------------------------

    async def dispatch(
        self, name: str, raw_args: dict, context: ToolContext
    ) -> ToolResult:
        """Validate args, consult policy, then execute.

        Order (final shape; middle step is a no-op until Step 2.6 supplies a
        hook):
          1. resolve tool
          2. validate args against the tool's args_schema
          3. policy hook -> allow / deny / needs_approval
          4. dry-run short-circuit
          5. execute
        """
        tool = self.get(name)

        # 2. validate
        try:
            args = tool.args_model(raw_args)
        except ValidationError as exc:
            return ToolResult(
                status="error",
                error=f"invalid args for {name!r}: {exc.error_count()} error(s)",
                metadata={"validation_errors": exc.errors(include_url=False)},
            )

        # 3. policy hook (Step 2.6). No hook -> allow.
        if self._policy_hook is not None and not context.auto_approve:
            verdict = await self._policy_hook(tool, args, context)
            if verdict is not None:
                return verdict

        # 4. dry-run: report what would have run, don't execute.
        if context.dry_run:
            return ToolResult(
                status="needs_approval",
                metadata={
                    "dry_run": True,
                    "tool": name,
                    "risk": int(tool.risk),
                    "args": args.model_dump(),
                },
            )

        # 5. execute
        return await tool.execute(args, context)
