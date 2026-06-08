"""Tests for decorator-based provider auto-discovery (Phase A)."""

from __future__ import annotations

import pytest

from newton.providers import (
    Provider,
    ProviderRegistry,
    discover_providers,
    register_all,
    register_provider,
)
from newton.providers.base import CostModel, ProviderResult


def test_builtin_providers_discovered():
    """The two demo providers self-register and are discoverable."""
    classes = discover_providers("newton.providers.builtin")
    names = sorted(c.name for c in classes)
    assert "echo_loud" in names
    assert "echo_quiet" in names


def test_register_all_populates_registry():
    registry = ProviderRegistry()
    instances = register_all(registry, "newton.providers.builtin")
    names = {p.name for p in instances}
    # Demo providers must be present; other builtins (e.g. embedding) may be
    # discovered too, so assert membership rather than an exact set.
    assert {"echo_loud", "echo_quiet"} <= names
    assert "demo.echo" in registry.capabilities()
    listed = sorted(p.name for p in registry.list_providers("demo.echo"))
    assert listed == ["echo_loud", "echo_quiet"]


def test_decorator_requires_name():
    with pytest.raises(ValueError, match="name"):

        @register_provider
        class NoName(Provider):
            capability = "x.y"

            async def execute(self, request):  # pragma: no cover
                return ProviderResult(ok=True)

            async def health_check(self):  # pragma: no cover
                return True


def test_decorator_requires_capability():
    with pytest.raises(ValueError, match="capability"):

        @register_provider
        class NoCap(Provider):
            name = "nocap"

            async def execute(self, request):  # pragma: no cover
                return ProviderResult(ok=True)

            async def health_check(self):  # pragma: no cover
                return True


def test_decorator_rejects_duplicate():
    @register_provider
    class FirstThing(Provider):
        name = "dup_thing"
        capability = "test.dup"
        cost_model = CostModel.FREE

        async def execute(self, request):  # pragma: no cover
            return ProviderResult(ok=True)

        async def health_check(self):  # pragma: no cover
            return True

    with pytest.raises(ValueError, match="duplicate"):

        @register_provider
        class SecondThing(Provider):
            name = "dup_thing"  # same (capability, name)
            capability = "test.dup"

            async def execute(self, request):  # pragma: no cover
                return ProviderResult(ok=True)

            async def health_check(self):  # pragma: no cover
                return True


def test_decorator_idempotent_same_class():
    """Decorating the identical class twice is harmless (re-import case)."""

    @register_provider
    class Reimported(Provider):
        name = "reimport_me"
        capability = "test.reimport"

        async def execute(self, request):  # pragma: no cover
            return ProviderResult(ok=True)

        async def health_check(self):  # pragma: no cover
            return True

    # Decorating the same object again must not raise.
    again = register_provider(Reimported)
    assert again is Reimported
