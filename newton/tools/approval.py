"""Approval channels: how Newton asks sir to approve a gated tool call.

The policy layer decides *whether* approval is needed (newton/tools/policy.py).
An ApprovalChannel decides *how* the question is put and answered. Block 2
ships a blocking CLI channel and an auto channel (always-yes, used in tests
and headless runs). Block 4+ may add voice / push / async channels behind the
same ABC without touching dispatch or policy.

A channel only ever sees calls that already need approval, so its single
job is to return a yes/no (with an optional reason).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ApprovalRequest:
    """Everything a channel needs to present one approval decision."""

    tool_name: str
    risk_level: int
    persona_id: str
    user_id: str
    args_summary: str
    policy_source: str  # "db" | "risk_default"


@dataclass(frozen=True)
class ApprovalOutcome:
    """A channel's answer."""

    approved: bool
    decision: str  # "approved" | "denied" | "timeout"
    reason: str | None = None


class ApprovalChannel(ABC):
    """Asks for approval on a gated tool call."""

    #: Short label recorded in the audit log (tool_approvals.channel).
    name: str = "abstract"

    @abstractmethod
    async def request(self, req: ApprovalRequest) -> ApprovalOutcome:
        """Present the request and return the outcome."""
        raise NotImplementedError


class AutoApproveChannel(ApprovalChannel):
    """Always approves. For tests and explicit headless auto-run.

    Distinct from ``ToolContext.auto_approve`` (which bypasses the policy
    hook entirely and logs nothing): a call through this channel is still
    gated and still written to the audit log, it just answers yes.
    """

    name = "auto"

    async def request(self, req: ApprovalRequest) -> ApprovalOutcome:
        return ApprovalOutcome(approved=True, decision="approved")


class DenyChannel(ApprovalChannel):
    """Always denies. Safe default when no interactive channel is available."""

    name = "deny"

    async def request(self, req: ApprovalRequest) -> ApprovalOutcome:
        return ApprovalOutcome(
            approved=False, decision="denied", reason="no approval channel"
        )


class CLIApprovalChannel(ApprovalChannel):
    """Blocking stdin prompt. Block 2's interactive approver.

    ``input_fn`` / ``output_fn`` are injectable so tests can drive the prompt
    without real stdin. Defaults are builtins ``input`` and ``print``.
    """

    name = "cli"

    def __init__(
        self,
        input_fn: Any = input,
        output_fn: Any = print,
    ) -> None:
        self._input = input_fn
        self._output = output_fn

    async def request(self, req: ApprovalRequest) -> ApprovalOutcome:
        self._output(
            f"\n[approval] {req.tool_name} (risk {req.risk_level}) "
            f"requested by {req.user_id}/{req.persona_id}"
        )
        self._output(f"[approval] args: {req.args_summary}")
        self._output(f"[approval] policy: {req.policy_source}")
        answer = str(self._input("[approval] allow this call? [y/N] ")).strip().lower()
        if answer in ("y", "yes"):
            return ApprovalOutcome(approved=True, decision="approved")
        return ApprovalOutcome(
            approved=False, decision="denied", reason="declined at CLI"
        )


__all__ = [
    "ApprovalChannel",
    "ApprovalOutcome",
    "ApprovalRequest",
    "AutoApproveChannel",
    "CLIApprovalChannel",
    "DenyChannel",
]
