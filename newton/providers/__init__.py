"""Newton provider layer (Block 2)."""

from newton.providers.base import CostModel, Provider, ProviderResult
from newton.providers.registry import ProviderError, ProviderRegistry

__all__ = [
    "CostModel",
    "Provider",
    "ProviderError",
    "ProviderRegistry",
    "ProviderResult",
    "register_demo_providers",
]


def register_demo_providers(registry: ProviderRegistry) -> None:
    """Register the block-2 demo providers (capability ``demo.echo``)."""
    from newton.providers.builtin.echo_loud import EchoLoudProvider
    from newton.providers.builtin.echo_quiet import EchoQuietProvider

    registry.register(EchoLoudProvider())
    registry.register(EchoQuietProvider())
