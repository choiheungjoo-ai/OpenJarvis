"""Step 3.1 smoke test — Qdrant is reachable and qdrant-client works.

This test hits a real Qdrant. Block 3 cannot proceed without one, so
making the test require a live instance is a feature, not a bug:

    scripts/newton/qdrant-up.sh

If Qdrant is *not* reachable the test fails with a clear message and a
hint, rather than skipping silently.

Skip with ``-k 'not qdrant'`` or ``-m 'not qdrant'`` if needed during
unrelated work.
"""

from __future__ import annotations

import os

import pytest

from newton.vault import qdrant_client as qc

pytestmark = pytest.mark.qdrant


def test_qdrant_url_default():
    assert qc.qdrant_url() == "http://localhost:6333"


def test_qdrant_url_env_override(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://localhost:9999")
    assert qc.qdrant_url() == "http://localhost:9999"


def test_qdrant_health_live():
    """Qdrant answers /healthz. Requires ``scripts/newton/qdrant-up.sh``."""
    health = qc.check_health()
    if not health.ok:
        pytest.fail(
            f"Qdrant is not reachable at {health.url}: {health.detail}\n"
            "Hint: run scripts/newton/qdrant-up.sh"
        )
    assert "passed" in health.detail


def test_qdrant_health_unreachable(monkeypatch):
    """A bogus URL produces an ok=False QdrantHealth, never raises."""
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:1")  # nothing listens
    health = qc.check_health(timeout=0.5)
    assert health.ok is False
    assert health.detail  # populated


def test_get_client_returns_qdrant_client():
    """get_client() returns an instance of the real QdrantClient."""
    from qdrant_client import QdrantClient

    client = qc.get_client()
    assert isinstance(client, QdrantClient)


def test_get_client_raises_on_unreachable(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:1")
    with pytest.raises(qc.QdrantError, match="not reachable"):
        qc.get_client()


def test_collections_endpoint_exists():
    """A live cluster has /collections (we don't care what's in it)."""
    import httpx

    response = httpx.get(f"{qc.qdrant_url()}/collections", timeout=2.0)
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("status") == "ok"
    assert "collections" in payload.get("result", {})


# Defensive: prevent accidental commits if QDRANT_URL is set system-wide
# to something other than localhost in CI.
def test_smoke_does_not_silently_run_against_prod():
    url = qc.qdrant_url()
    assert os.environ.get("NEWTON_ENV") != "prod", (
        f"refusing to run qdrant smoke against {url} in prod env"
    )
