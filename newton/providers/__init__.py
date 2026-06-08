"""Newton provider layer (Block 2+).

Providers self-register via ``@register_provider`` (see registration.py).
``register_all(registry, "newton.providers.builtin")`` discovers and
instantiates them — no hardcoded provider list.
"""

from newton.providers.base import CostModel, Provider, ProviderResult
from newton.providers.registration import (
    discover_providers,
    register_all,
    register_provider,
)
from newton.providers.registry import ProviderError, ProviderRegistry

__all__ = [
    "CostModel",
    "Provider",
    "ProviderError",
    "ProviderRegistry",
    "ProviderResult",
    "discover_providers",
    "register_all",
    "register_provider",
]
