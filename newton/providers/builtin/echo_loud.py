"""echo_loud — demo provider for capability ``demo.echo``.

Returns the text uppercased. Paired with echo_quiet to exercise hot-swap in
block 2 before real providers exist.
"""

from __future__ import annotations

from typing import Any

from newton.providers.base import CostModel, Provider, ProviderResult
from newton.providers.registration import register_provider


@register_provider
class EchoLoudProvider(Provider):
    name = "echo_loud"
    capability = "demo.echo"
    cost_model = CostModel.FREE
    free_quota = None

    async def execute(self, request: dict[str, Any]) -> ProviderResult:
        text = str(request.get("text", ""))
        return ProviderResult(ok=True, data={"text": text.upper()})

    async def health_check(self) -> bool:
        return True


__all__ = ["EchoLoudProvider"]
