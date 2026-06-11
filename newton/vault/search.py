"""ACL-filtered RAG search over the vault.

Embeds a query, then asks Qdrant for the nearest chunks the caller is allowed
to see. Access semantics (option "C"):

  1. status == status_filter          (default "canonical")
  2. user gate (OR):                  user_id in read_users OR owner == user_id
  3. persona restriction:             read_personas contains persona_id OR "*"

For (3) to be a single Qdrant filter, the indexer normalises an empty
read_personas to ["*"] at index time, so "no persona restriction" is encoded
as the wildcard. A note readable by any persona therefore matches any
persona_id via the "*" entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from newton.system_config import SystemConfig, load_system_config
from newton.vault.embeddings import EmbeddingService

_COLLECTION = "vault"


@dataclass
class SearchHit:
    """One search result."""

    note_id: int
    chunk_index: int
    path: str
    score: float
    text: str
    owner_user_id: str | None
    status: str
    tags: list[str]


def _acl_filter(user_id: str, persona_id: str, status_filter: str) -> Any:
    """Build the Qdrant payload filter for option-C access semantics."""
    from qdrant_client import models

    return models.Filter(
        must=[
            models.FieldCondition(
                key="status", match=models.MatchValue(value=status_filter)
            ),
            # user gate: read_users contains user_id OR owner == user_id
            models.Filter(
                should=[
                    models.FieldCondition(
                        key="read_users", match=models.MatchAny(any=[user_id])
                    ),
                    models.FieldCondition(
                        key="owner_user_id",
                        match=models.MatchValue(value=user_id),
                    ),
                ]
            ),
            # persona restriction: read_personas contains persona_id OR "*"
            models.FieldCondition(
                key="read_personas",
                match=models.MatchAny(any=[persona_id, "*"]),
            ),
        ]
    )


async def search(
    query: str,
    user_id: str,
    persona_id: str,
    *,
    limit: int = 5,
    status_filter: str = "canonical",
    config: SystemConfig | None = None,
) -> list[SearchHit]:
    """Semantic search over the vault, filtered by ACL for (user, persona)."""
    from newton.vault.qdrant_client import get_client

    if config is None:
        config = load_system_config()

    service = EmbeddingService.from_config(config.embedding)
    client = get_client()

    if not client.collection_exists(_COLLECTION):
        return []

    query_vector = await service.encode_one(query)
    flt = _acl_filter(user_id, persona_id, status_filter)

    response = client.query_points(
        collection_name=_COLLECTION,
        query=query_vector,
        query_filter=flt,
        limit=limit,
        with_payload=True,
    )

    hits: list[SearchHit] = []
    for point in response.points:
        p = point.payload or {}
        hits.append(
            SearchHit(
                note_id=p.get("note_id", -1),
                chunk_index=p.get("chunk_index", -1),
                path=p.get("path", ""),
                score=point.score,
                text=p.get("text", ""),
                owner_user_id=p.get("owner_user_id"),
                status=p.get("status", ""),
                tags=p.get("tags", []),
            )
        )
    return hits


__all__ = ["SearchHit", "search"]
