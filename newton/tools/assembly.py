"""Assembly helpers shared by the CLI (and reusable by other surfaces).

Keeps cli.py thin: these wire builtins + the policy/approval hook into a
ToolRegistry, and demo providers into a ProviderRegistry, in one place.
"""

from __future__ import annotations

from typing import Any

from newton.db import get_session
from newton.providers import ProviderRegistry, register_demo_providers
from newton.tools.approval import AutoApproveChannel, CLIApprovalChannel
from newton.tools.builtin import register_builtins
from newton.tools.policy import build_policy_hook
from newton.tools.registry import ToolRegistry


def build_tool_registry(
    *,
    auto_approve: bool = False,
    input_fn: Any = input,
    output_fn: Any = print,
) -> ToolRegistry:
    """A ToolRegistry with builtins registered and the approval hook wired.

    auto_approve=True uses an AutoApproveChannel (still gated + logged);
    otherwise a blocking CLIApprovalChannel prompts on stdin. ``input_fn`` /
    ``output_fn`` are injectable so tests can drive the prompt.
    """
    channel = (
        AutoApproveChannel()
        if auto_approve
        else CLIApprovalChannel(input_fn=input_fn, output_fn=output_fn)
    )
    hook = build_policy_hook(get_session, approval_channel=channel)
    registry = ToolRegistry(policy_hook=hook)
    register_builtins(registry)
    return registry


def build_provider_registry() -> ProviderRegistry:
    """A ProviderRegistry with demo providers and DB-backed permanent swaps."""
    registry = ProviderRegistry(session_factory=get_session)
    register_demo_providers(registry)
    return registry


__all__ = ["build_provider_registry", "build_tool_registry"]
