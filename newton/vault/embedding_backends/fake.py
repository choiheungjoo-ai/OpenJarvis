"""Deterministic fake embedding backend for tests.

Produces stable, repeatable vectors from a hash of the input text — same
text always yields the same vector, different texts yield different ones.
No network, no model, instant. Lets EmbeddingService logic be tested without
a live TEI.

The vectors are L2-normalised so cosine similarity behaves sensibly, but
they carry no semantic meaning — do not assert on semantic closeness with
this backend; use the real TEI backend (``@pytest.mark.embedding``) for that.
"""

from __future__ import annotations

import hashlib
import math

from newton.vault.embedding_backends.base import (
    EmbeddingBackend,
    register_embedding_backend,
)

_DEFAULT_DIM = 1024


@register_embedding_backend
class FakeEmbeddingBackend(EmbeddingBackend):
    """Hash-based deterministic embeddings. Test use only."""

    name = "fake"

    def __init__(self, dim: int = _DEFAULT_DIM):
        self._dim = dim

    def _vector(self, text: str) -> list[float]:
        # Expand a digest into ``dim`` floats deterministically.
        raw = bytearray()
        counter = 0
        while len(raw) < self._dim:
            h = hashlib.sha256(f"{counter}:{text}".encode()).digest()
            raw.extend(h)
            counter += 1
        vals = [(b / 255.0) * 2.0 - 1.0 for b in raw[: self._dim]]
        norm = math.sqrt(sum(v * v for v in vals)) or 1.0
        return [v / norm for v in vals]

    async def encode(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    async def dimension(self) -> int:
        return self._dim

    async def health(self) -> bool:
        return True


__all__ = ["FakeEmbeddingBackend"]
