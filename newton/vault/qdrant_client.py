"""Minimal Qdrant client wrapper for Newton.

Step 3.1 ships only what's needed to confirm Qdrant is reachable and
return a configured client. Collection / point operations come in 3.5.

Configuration:
    QDRANT_URL — full base URL, defaults to http://localhost:6333.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from qdrant_client import QdrantClient

_DEFAULT_URL = "http://localhost:6333"


class QdrantError(RuntimeError):
    """Raised when Qdrant is unreachable or returns an unexpected response."""


@dataclass(frozen=True)
class QdrantHealth:
    """Result of a Qdrant health probe."""

    ok: bool
    url: str
    detail: str  # short human-readable summary; "healthz check passed" on success


def qdrant_url() -> str:
    """Return the configured Qdrant base URL."""
    return os.environ.get("QDRANT_URL", _DEFAULT_URL)


def check_health(timeout: float = 2.0) -> QdrantHealth:
    """Probe ``GET /healthz``. Never raises; returns a QdrantHealth."""
    url = qdrant_url()
    target = f"{url.rstrip('/')}/healthz"
    try:
        response = httpx.get(target, timeout=timeout)
    except httpx.HTTPError as e:
        return QdrantHealth(ok=False, url=url, detail=f"{type(e).__name__}: {e}")

    body = response.text.strip()
    if response.status_code == 200 and "passed" in body:
        return QdrantHealth(ok=True, url=url, detail=body)
    return QdrantHealth(
        ok=False, url=url, detail=f"HTTP {response.status_code}: {body[:120]}"
    )


def get_client() -> QdrantClient:
    """Return a configured qdrant-client. Raises QdrantError if unreachable."""
    health = check_health()
    if not health.ok:
        raise QdrantError(f"Qdrant not reachable at {health.url}: {health.detail}")
    try:
        from qdrant_client import QdrantClient
    except ImportError as e:
        raise QdrantError(
            "qdrant-client is not installed; run `uv add qdrant-client`"
        ) from e
    return QdrantClient(url=health.url)


__all__ = ["QdrantError", "QdrantHealth", "check_health", "get_client", "qdrant_url"]
