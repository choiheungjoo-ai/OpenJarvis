"""TEI (text-embeddings-inference) embedding backend.

Talks to a running TEI service over HTTP. No PyTorch / CUDA in the Newton
process — the GPU work happens inside the TEI container. This is the default
backend for Newton; the model it serves (BGE-M3 by default) is configured in
``config/newton.yaml`` and on the TEI container's command line.

Endpoints used:
    POST /embed   {"inputs": str | list[str]}  -> list[list[float]]
    GET  /health                                -> 200 when ready

Dimension is discovered by embedding a short probe once and caching the
length, because TEI's /info does not report the vector dimension.
"""

from __future__ import annotations

import asyncio

import httpx

from newton.vault.embedding_backends.base import (
    EmbeddingBackend,
    EmbeddingError,
    register_embedding_backend,
)


@register_embedding_backend
class TeiBackend(EmbeddingBackend):
    """Embeds via an HTTP TEI service."""

    name = "tei"

    def __init__(self, url: str = "http://localhost:8080", timeout_s: float = 30.0):
        self._url = url.rstrip("/")
        self._timeout = timeout_s
        self._dimension: int | None = None
        self._dim_lock = asyncio.Lock()

    async def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(f"{self._url}/embed", json={"inputs": texts})
        except httpx.HTTPError as e:
            raise EmbeddingError(f"TEI request failed at {self._url}: {e}") from e

        if resp.status_code != 200:
            raise EmbeddingError(
                f"TEI returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        vectors = resp.json()
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbeddingError(
                f"TEI returned {len(vectors) if isinstance(vectors, list) else '?'} "
                f"vectors for {len(texts)} inputs"
            )
        return vectors

    async def dimension(self) -> int:
        if self._dimension is not None:
            return self._dimension
        async with self._dim_lock:
            if self._dimension is not None:  # re-check after acquiring
                return self._dimension
            probe = await self.encode(["dimension probe"])
            if not probe or not probe[0]:
                raise EmbeddingError("TEI returned an empty probe embedding")
            self._dimension = len(probe[0])
            return self._dimension

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{self._url}/health")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False


__all__ = ["TeiBackend"]
