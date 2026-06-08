"""Embedding backend abstraction.

An embedding backend turns text into dense vectors. Newton treats this as an
external capability (like an LLM): the backend may be an HTTP service (TEI),
a future in-process model, or a fake for tests. ``EmbeddingService`` depends
only on this interface, never on a concrete backend.

Backends opt in with ``@register_embedding_backend`` (same philosophy as the
provider registry): the marker names exactly the live backends, so abstract
bases and helpers are not picked up by discovery.

Dimension note: the vector dimension is a property of the loaded model, not
something we hardcode. Concrete backends discover it at runtime (e.g. TEI by
embedding a probe string) so swapping the model needs no code change.
"""

from __future__ import annotations

import importlib
import pkgutil
from abc import ABC, abstractmethod
from collections.abc import Iterable
from types import ModuleType

# Registry of backend classes, populated by the decorator at import time.
_BACKENDS: dict[str, type["EmbeddingBackend"]] = {}


class EmbeddingError(RuntimeError):
    """Raised when an embedding backend fails or is misconfigured."""


class EmbeddingBackend(ABC):
    """One way to turn text into dense vectors.

    Subclasses set ``name`` and implement async ``encode`` / ``health`` and
    the ``dimension`` discovery. ``encode`` takes a batch and returns one
    vector per input, in order.
    """

    name: str

    @abstractmethod
    async def encode(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns one vector per input, in order."""
        raise NotImplementedError

    @abstractmethod
    async def dimension(self) -> int:
        """Return the vector dimension of this backend's model.

        Implementations should discover this at runtime (not hardcode it)
        and may cache the result.
        """
        raise NotImplementedError

    @abstractmethod
    async def health(self) -> bool:
        """Return True if the backend is reachable / usable right now."""
        raise NotImplementedError


def register_embedding_backend(
    cls: type[EmbeddingBackend],
) -> type[EmbeddingBackend]:
    """Class decorator: mark an EmbeddingBackend subclass for discovery."""
    name = getattr(cls, "name", None)
    if not isinstance(name, str) or not name:
        raise ValueError(f"{cls.__name__} must set a non-empty class attr 'name'")
    existing = _BACKENDS.get(name)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"duplicate embedding backend {name!r}: "
            f"{existing.__name__} and {cls.__name__}"
        )
    _BACKENDS[name] = cls
    return cls


def _iter_modules(package: ModuleType) -> Iterable[str]:
    for info in pkgutil.iter_modules(package.__path__):
        yield f"{package.__name__}.{info.name}"


def discover_backends(
    package_name: str = "newton.vault.embedding_backends",
) -> dict[str, type[EmbeddingBackend]]:
    """Import every module in the package so decorators run; return registry."""
    package = importlib.import_module(package_name)
    for module_name in _iter_modules(package):
        importlib.import_module(module_name)
    return dict(_BACKENDS)


def get_backend_class(name: str) -> type[EmbeddingBackend]:
    """Return the backend class registered under ``name``, discovering first."""
    backends = discover_backends()
    try:
        return backends[name]
    except KeyError:
        available = ", ".join(sorted(backends)) or "(none)"
        raise EmbeddingError(
            f"unknown embedding backend {name!r}; available: {available}"
        ) from None


__all__ = [
    "EmbeddingBackend",
    "EmbeddingError",
    "discover_backends",
    "get_backend_class",
    "register_embedding_backend",
]
