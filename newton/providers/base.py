"""Provider base abstractions.

A capability (e.g. ``web.search``) can have several competing providers
(SearXNG, Brave, ...). Exactly one is active at a time; sir can hot-swap at
runtime without restart. Block 2 ships the abstraction and registry; real
providers arrive in blocks 6/7/9.

Layering note: providers sit *below* tools. A tool may call a provider and
wrap its ``ProviderResult`` into the tool's own ``ToolResult``. The two
result types are deliberately separate — tools carry approval/risk status,
providers carry usage/cost telemetry.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel


class CostModel(str, Enum):
    """How a provider is billed. Drives default-selection priority."""

    FREE = "free"  # unlimited, no cost (e.g. self-hosted SearXNG)
    FREE_TIER = "free_tier"  # free up to a monthly quota
    PAID = "paid"  # always costs money


class ProviderResult(BaseModel):
    """What every provider returns.

    ``provider_name`` records which implementation answered (useful after a
    one-shot swap). ``cost`` / ``usage`` feed the registry's telemetry.
    """

    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    provider_name: str | None = None
    cost: float = 0.0
    usage: dict[str, Any] = {}


class Provider(ABC):
    """One implementation of a capability.

    Subclasses set the class attributes and implement ``execute`` and
    ``health_check``. ``free_quota`` is None for unlimited/paid providers.
    """

    name: str
    capability: str
    cost_model: CostModel = CostModel.FREE
    free_quota: int | None = None

    def __init__(self) -> None:
        # Per-process usage counter; telemetry reads this. Persistent quota
        # accounting across restarts is a later-block concern.
        self.used_this_session: int = 0

    @abstractmethod
    async def execute(self, request: dict[str, Any]) -> ProviderResult:
        """Run the capability for one request."""
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is reachable / usable right now."""
        raise NotImplementedError

    def _priority(self) -> int:
        """Default-selection priority: lower wins. Free before paid."""
        return {
            CostModel.FREE: 0,
            CostModel.FREE_TIER: 1,
            CostModel.PAID: 2,
        }[self.cost_model]


__all__ = ["CostModel", "Provider", "ProviderResult"]
