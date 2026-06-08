"""Unit tests for embedding backends and EmbeddingService (fake backend).

These never touch the network. Semantic quality is verified separately
against real TEI in test_embeddings_tei.py (@pytest.mark.embedding).
"""

from __future__ import annotations

import pytest

from newton.system_config import EmbeddingConfig
from newton.vault.embedding_backends import (
    EmbeddingError,
    discover_backends,
    get_backend_class,
)
from newton.vault.embedding_backends.fake import FakeEmbeddingBackend
from newton.vault.embeddings import EmbeddingService

# -- backend discovery --------------------------------------------------------


def test_backends_discovered():
    backends = discover_backends()
    assert "tei" in backends
    assert "fake" in backends


def test_get_backend_class_known():
    assert get_backend_class("fake") is FakeEmbeddingBackend


def test_get_backend_class_unknown():
    with pytest.raises(EmbeddingError, match="unknown embedding backend"):
        get_backend_class("does-not-exist")


# -- fake backend semantics ---------------------------------------------------


@pytest.mark.asyncio
async def test_fake_deterministic():
    b = FakeEmbeddingBackend()
    v1 = await b.encode(["hello"])
    v2 = await b.encode(["hello"])
    assert v1 == v2  # identical input -> identical vector


@pytest.mark.asyncio
async def test_fake_distinct_inputs_differ():
    b = FakeEmbeddingBackend()
    [v_a], [v_b] = await b.encode(["a"]), await b.encode(["b"])
    assert v_a != v_b


@pytest.mark.asyncio
async def test_fake_dimension_and_shape():
    b = FakeEmbeddingBackend(dim=1024)
    assert await b.dimension() == 1024
    vecs = await b.encode(["x", "y", "z"])
    assert len(vecs) == 3
    assert all(len(v) == 1024 for v in vecs)


@pytest.mark.asyncio
async def test_fake_normalised():
    b = FakeEmbeddingBackend(dim=64)
    [v] = await b.encode(["normalise me"])
    norm = sum(x * x for x in v) ** 0.5
    assert abs(norm - 1.0) < 1e-6


@pytest.mark.asyncio
async def test_fake_custom_dimension():
    b = FakeEmbeddingBackend(dim=8)
    assert await b.dimension() == 8
    [v] = await b.encode(["short"])
    assert len(v) == 8


# -- EmbeddingService ---------------------------------------------------------


@pytest.mark.asyncio
async def test_service_encode_empty():
    svc = EmbeddingService(FakeEmbeddingBackend())
    assert await svc.encode([]) == []


@pytest.mark.asyncio
async def test_service_encode_one():
    svc = EmbeddingService(FakeEmbeddingBackend(dim=32))
    v = await svc.encode_one("solo")
    assert len(v) == 32


@pytest.mark.asyncio
async def test_service_batching_preserves_order_and_count():
    # batch_size smaller than input forces multiple backend calls.
    svc = EmbeddingService(FakeEmbeddingBackend(dim=16), batch_size=2)
    texts = [f"text-{i}" for i in range(5)]
    vecs = await svc.encode(texts)
    assert len(vecs) == 5
    # Order preserved: re-encoding text-0 alone equals the first vector.
    [solo] = await svc.encode(["text-0"])
    assert vecs[0] == solo


@pytest.mark.asyncio
async def test_service_dimension_delegates():
    svc = EmbeddingService(FakeEmbeddingBackend(dim=128))
    assert await svc.dimension() == 128


@pytest.mark.asyncio
async def test_service_health():
    svc = EmbeddingService(FakeEmbeddingBackend())
    assert await svc.health() is True


@pytest.mark.asyncio
async def test_service_backend_name():
    svc = EmbeddingService(FakeEmbeddingBackend())
    assert svc.backend_name == "fake"


# -- from_config --------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_from_config_fake():
    cfg = EmbeddingConfig(backend="fake")
    svc = EmbeddingService.from_config(cfg)
    assert svc.backend_name == "fake"
    v = await svc.encode_one("via config")
    assert len(v) == 1024  # fake default dim


def test_service_from_config_tei_builds_without_contacting():
    """Building a TEI-backed service must not contact TEI (lazy)."""
    cfg = EmbeddingConfig(backend="tei")
    cfg.tei.url = "http://127.0.0.1:1"  # nothing there
    svc = EmbeddingService.from_config(cfg)  # must not raise
    assert svc.backend_name == "tei"
