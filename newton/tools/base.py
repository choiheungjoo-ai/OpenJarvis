"""Newton tool-layer base abstractions.

Step 2.2 — locks the interface every Newton tool follows. No dispatch,
policy, or approval logic here; those arrive in Steps 2.3-2.6.

Decisions from Step 2.1 (docs/newton/block-2-investigation.md):
  - Pydantic v2 only.
  - Five risk levels (0..4), all exercised by real tools.
  - Newton owns this layer entirely; nothing imported from openjarvis.tools.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, ClassVar, Literal

from pydantic import BaseModel


class RiskLevel(IntEnum):
    """A tool's exposure rating. Drives the default approval policy.

    The scale is confirmed at 5 levels in Step 2.1: every level is
    exercised by a real tool, so it does not collapse to 4 or 3.
    """

    SAFE = 0  # pure compute / echo — no side effects
    READ_LOCAL = 1  # read local fs / system info
    WRITE_LOCAL = 2  # write local fs
    READ_NETWORK = 3  # read over the network
    WRITE_NETWORK = 4  # write / send over the network


class ToolResult(BaseModel):
    """The wrapper returned by every tool call.

    ``status`` is the contract other layers branch on:
      - ok             — executed successfully, see ``data``
      - error          — execution failed, see ``error``
      - needs_approval — dispatch stopped pending approval (e.g. dry-run)
      - denied         — policy or approver refused the call
    """

    status: Literal["ok", "error", "needs_approval", "denied"]
    data: dict[str, Any] | None = None
    error: str | None = None
    metadata: dict[str, Any] = {}


@dataclass
class ToolContext:
    """Per-call context handed to ``Tool.execute``.

    ``auto_approve`` short-circuits the approval prompt so pytest never
    blocks on stdin (see Step 2.6). ``dry_run`` asks dispatch to return the
    would-have-been action instead of executing it.
    """

    user_id: str
    persona_id: str
    session_id: str | None = None
    dry_run: bool = False
    auto_approve: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class Tool(ABC):
    """Abstract base for every Newton tool.

    Subclasses set the class-level attributes and implement ``execute``.
    ``args_schema`` / ``returns_schema`` are Pydantic v2 models describing
    the call's inputs and outputs.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    risk: ClassVar[RiskLevel]
    args_schema: ClassVar[type[BaseModel]]
    returns_schema: ClassVar[type[BaseModel]]

    @abstractmethod
    async def execute(self, args: BaseModel, context: ToolContext) -> ToolResult:
        """Run the tool. Must return a :class:`ToolResult`."""
        raise NotImplementedError

    def args_model(self, raw: dict[str, Any]) -> BaseModel:
        """Validate and coerce a raw arg dict into the tool's args model."""
        return self.args_schema(**raw)
