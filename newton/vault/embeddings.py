"""EmbeddingService — Newton's text→vector entry point.

Backend-agnostic: it picks a backend by name from config (or one injected
directly, for tests), then delegates. Callers never import a concrete
backend. Encoding is batched to respect the backend's batch limit.

    service = EmbeddingService.from_config()
    vectors = await service.encode(["안녕", "hello"])
    dim = await service.dimension()
"""

from __future__ import annotations

from newton.system_config import EmbeddingConfig, load_system_config
from newton.vault.embedding_backends.base import (
    EmbeddingBackend,
    get_backend_class,
)

# Fallback batch size when neither config nor backend specifies one.
_DEFAULT_BATCH = 32


class EmbeddingService:
    """Turns text into vectors via a configured backend."""

    def __init__(self, backend: EmbeddingBackend, batch_size: int | None = None):
        self._backend = backend
        self._batch_size = batch_size or _DEFAULT_BATCH

    # -- construction ---------------------------------------------------------

    @classmethod
    def from_config(cls, config: EmbeddingConfig | None = None) -> EmbeddingService:
        """Build from an EmbeddingConfig (loads system config if not given)."""
        if config is None:
            config = load_system_config().embedding

        backend_cls = get_backend_class(config.backend)
        backend = cls._instantiate(backend_cls, config)
        return cls(backend, batch_size=config.batch_size)

    @staticmethod
    def _instantiate(
        backend_cls: type[EmbeddingBackend], config: EmbeddingConfig
    ) -> EmbeddingBackend:
        """Instantiate a backend with the settings it needs.

        Each backend reads its own sub-section of the config. Kept explicit
        (rather than reflection) so construction is obvious and type-checked.
        """
        if config.backend == "tei":
            from newton.vault.embedding_backends.tei import TeiBackend

            return TeiBackend(url=config.tei.url, timeout_s=config.tei.timeout_s)
        # Backends with no required settings (e.g. fake) take no args.
        return backend_cls()

    @property
    def backend_name(self) -> str:
        return self._backend.name

    # -- operations -----------------------------------------------------------

    async def encode(self, texts: list[str]) -> list[list[float]]:
        """Embed texts, batching to the configured size. Order preserved."""
        if not texts:
            return []
        out: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            chunk = texts[start : start + self._batch_size]
            out.extend(await self._backend.encode(chunk))
        return out

    async def encode_one(self, text: str) -> list[float]:
        """Convenience: embed a single string."""
        result = await self.encode([text])
        return result[0]

    async def dimension(self) -> int:
        """Vector dimension of the active backend's model."""
        return await self._backend.dimension()

    async def health(self) -> bool:
        return await self._backend.health()


__all__ = ["EmbeddingService"]
