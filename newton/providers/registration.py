"""Provider auto-registration.

Providers opt in with the ``@register_provider`` decorator instead of being
named in a hardcoded list. ``discover_providers`` imports every module in a
package (so decorators run) and returns the registered classes;
``register_all`` instantiates them into a ProviderRegistry.

Why a decorator and not "every Provider subclass": a module may define
abstract bases or helper subclasses that should not be registered. The
decorator marks exactly the classes meant to be live.

Design note: registration collects *classes*, not instances. Instantiation
is deferred to ``register_all`` so importing a provider module has no side
effects (no DB, no network) beyond adding to the class registry.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterable
from types import ModuleType

from newton.providers.base import Provider
from newton.providers.registry import ProviderRegistry

# Module-level registry of provider classes, populated by the decorator at
# import time. Keyed by (capability, name) to catch accidental duplicates.
_REGISTERED: dict[tuple[str, str], type[Provider]] = {}


def register_provider(cls: type[Provider]) -> type[Provider]:
    """Class decorator: mark a Provider subclass for auto-registration.

    Validates the required class attributes are set, then records the class.
    Returns the class unchanged.
    """
    name = getattr(cls, "name", None)
    capability = getattr(cls, "capability", None)
    if not isinstance(name, str) or not name:
        raise ValueError(f"{cls.__name__} must set a non-empty class attr 'name'")
    if not isinstance(capability, str) or not capability:
        raise ValueError(f"{cls.__name__} must set a non-empty class attr 'capability'")

    key = (capability, name)
    existing = _REGISTERED.get(key)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"duplicate provider registration for capability={capability!r} "
            f"name={name!r}: {existing.__name__} and {cls.__name__}"
        )
    _REGISTERED[key] = cls
    return cls


def _iter_modules(package: ModuleType) -> Iterable[str]:
    """Yield fully-qualified names of all submodules in a package."""
    for info in pkgutil.iter_modules(package.__path__):
        yield f"{package.__name__}.{info.name}"


def discover_providers(package_name: str) -> list[type[Provider]]:
    """Import every module under ``package_name`` so decorators run.

    Returns the provider classes registered for modules in that package.
    Idempotent: importing an already-imported module is a no-op.
    """
    package = importlib.import_module(package_name)
    for module_name in _iter_modules(package):
        importlib.import_module(module_name)

    prefix = package_name + "."
    return [
        cls
        for cls in _REGISTERED.values()
        if cls.__module__ == package_name or cls.__module__.startswith(prefix)
    ]


def register_all(registry: ProviderRegistry, package_name: str) -> list[Provider]:
    """Discover providers in a package and register instances into ``registry``.

    Returns the instances registered, ordered by (capability, name) for
    deterministic behaviour.
    """
    classes = discover_providers(package_name)
    classes.sort(key=lambda c: (c.capability, c.name))
    instances: list[Provider] = []
    for cls in classes:
        instance = cls()
        registry.register(instance)
        instances.append(instance)
    return instances


def registered_classes() -> dict[tuple[str, str], type[Provider]]:
    """Return a copy of the current registry of provider classes (for tests)."""
    return dict(_REGISTERED)


__all__ = [
    "discover_providers",
    "register_all",
    "register_provider",
    "registered_classes",
]
