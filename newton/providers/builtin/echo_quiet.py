"""echo_quiet — demo provider for capability ``demo.echo``.

Returns the text lowercased. Paired with echo_loud to exercise hot-swap.
Marked free_tier so default-priority ordering (free before free_tier) is
also testable: echo_loud is the default, echo_quiet a registered alternate.
"""

from __future__ import annotations

from typing import Any

from newton.providers.base import CostModel, Provider, ProviderResult
from newton.providers.registration import register_provider


@register_provider
class EchoQuietProvider(Provider):
    name = "echo_quiet"
    capability = "demo.echo"
    cost_model = CostModel.FREE_TIER
    free_quota = 1000

    async def execute(self, request: dict[str, Any]) -> ProviderResult:
        text = str(request.get("text", ""))
        return ProviderResult(ok=True, data={"text": text.lower()})

    async def health_check(self) -> bool:
        return True


__all__ = ["EchoQuietProvider"]
