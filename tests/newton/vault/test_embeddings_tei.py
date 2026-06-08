"""Real-TEI embedding tests. Requires a running TEI service (BGE-M3).

    scripts/newton/tei-up.sh

Marked ``embedding`` so day-to-day runs can skip with ``-m "not embedding"``.
These verify the things the fake backend cannot: real dimension, multilingual
behaviour, and that semantically related text is closer than unrelated text.
"""

from __future__ import annotations

import math

import pytest

from newton.system_config import EmbeddingConfig
from newton.vault.embedding_backends.tei import TeiBackend
from newton.vault.embeddings import EmbeddingService

pytestmark = pytest.mark.embedding


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb)


async def _require_tei(backend: TeiBackend) -> None:
    if not await backend.health():
        pytest.fail(
            "TEI not reachable at its configured URL. "
            "Hint: run scripts/newton/tei-up.sh"
        )


@pytest.mark.asyncio
async def test_tei_dimension_is_1024():
    backend = TeiBackend()
    await _require_tei(backend)
    assert await backend.dimension() == 1024  # BGE-M3


@pytest.mark.asyncio
async def test_tei_encodes_korean_and_english():
    backend = TeiBackend()
    await _require_tei(backend)
    vecs = await backend.encode(["안녕하세요", "hello world"])
    assert len(vecs) == 2
    assert all(len(v) == 1024 for v in vecs)


@pytest.mark.asyncio
async def test_tei_semantic_similarity():
    """Related sentences should be closer than unrelated ones."""
    backend = TeiBackend()
    await _require_tei(backend)
    cat1, cat2, car = await backend.encode(
        [
            "The cat sat on the mat.",
            "A kitten rested on the rug.",
            "Quarterly revenue exceeded forecasts.",
        ]
    )
    sim_related = _cosine(cat1, cat2)
    sim_unrelated = _cosine(cat1, car)
    assert sim_related > sim_unrelated


@pytest.mark.asyncio
async def test_tei_cross_lingual_alignment():
    """BGE-M3 aligns translations across languages."""
    backend = TeiBackend()
    await _require_tei(backend)
    en, ko, unrelated = await backend.encode(
        [
            "I love machine learning.",
            "나는 기계 학습을 좋아한다.",
            "The weather is cold today.",
        ]
    )
    assert _cosine(en, ko) > _cosine(en, unrelated)


@pytest.mark.asyncio
async def test_service_from_config_tei_live():
    svc = EmbeddingService.from_config(EmbeddingConfig(backend="tei"))
    if not await svc.health():
        pytest.fail("TEI not reachable; run scripts/newton/tei-up.sh")
    v = await svc.encode_one("end to end through the service")
    assert len(v) == 1024
