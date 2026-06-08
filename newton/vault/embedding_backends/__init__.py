"""Embedding backends.

Modules here are auto-discovered via
``newton.vault.embedding_backends.base.discover_backends()``. Each backend
opts in with ``@register_embedding_backend``; there is no explicit list to
maintain here.
"""

from newton.vault.embedding_backends.base import (
    EmbeddingBackend,
    EmbeddingError,
    discover_backends,
    get_backend_class,
    register_embedding_backend,
)

__all__ = [
    "EmbeddingBackend",
    "EmbeddingError",
    "discover_backends",
    "get_backend_class",
    "register_embedding_backend",
]
