"""Vault indexer — chunk, embed, and store notes in Qdrant.

Pipeline (per note that needs indexing):
    read vault_notes row -> read file body -> chunk -> embed (TEI) ->
    delete old points for this note -> upsert new points (vector + ACL payload)

"Needs indexing" = the row's ``indexed_hash`` differs from its current
``content_hash`` (or is NULL). Because content_hash covers the whole raw file,
an ACL-only edit re-indexes too, refreshing the ACL snapshot in each point.

Qdrant is the single source of truth for chunks; there is no SQLite chunk
table. Old points are removed by filtering on ``note_id`` before re-insert, so
a note that shrinks from 5 chunks to 3 leaves no orphans.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from newton.system_config import SystemConfig, load_system_config
from newton.vault.chunker import chunk_text
from newton.vault.embeddings import EmbeddingService

_COLLECTION = "vault"
_PAYLOAD_TEXT_PREVIEW = 200  # chars of chunk text stored in payload


@dataclass
class IndexResult:
    notes_indexed: int = 0
    notes_skipped: int = 0
    chunks_upserted: int = 0
    notes_removed: int = 0
    errors: list[str] = field(default_factory=list)


def _qdrant():
    from newton.vault.qdrant_client import get_client

    return get_client()


def _ensure_collection(client: Any, dim: int) -> None:
    """Create the vault collection + payload indexes if absent."""
    from qdrant_client import models

    if not client.collection_exists(_COLLECTION):
        client.create_collection(
            collection_name=_COLLECTION,
            vectors_config=models.VectorParams(
                size=dim, distance=models.Distance.COSINE
            ),
        )
        for field_name, schema in [
            ("note_id", models.PayloadSchemaType.INTEGER),
            ("owner_user_id", models.PayloadSchemaType.KEYWORD),
            ("read_users", models.PayloadSchemaType.KEYWORD),
            ("read_personas", models.PayloadSchemaType.KEYWORD),
            ("status", models.PayloadSchemaType.KEYWORD),
        ]:
            client.create_payload_index(
                collection_name=_COLLECTION,
                field_name=field_name,
                field_schema=schema,
            )


def _delete_note_points(client: Any, note_id: int) -> None:
    from qdrant_client import models

    client.delete(
        collection_name=_COLLECTION,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="note_id", match=models.MatchValue(value=note_id)
                    )
                ]
            )
        ),
    )


def _point_id(note_id: int, chunk_index: int) -> int:
    return note_id * 10000 + chunk_index


def _payload(row: Any, chunk_index: int, text: str) -> dict[str, Any]:
    return {
        "note_id": row.note_id,
        "chunk_index": chunk_index,
        "path": row.path,
        "owner_user_id": row.owner_user_id,
        "read_users": row.read_users,
        "read_personas": row.read_personas or ["*"],
        "status": row.status,
        "tags": row.tags,
        "text": text[:_PAYLOAD_TEXT_PREVIEW],
    }


async def index_vault(
    session: Any,
    config: SystemConfig | None = None,
    *,
    force: bool = False,
) -> IndexResult:
    """Index notes whose content changed since last index (or all if force)."""
    from qdrant_client import models
    from sqlalchemy import select

    from newton.models.vault import VaultNoteRecord

    if config is None:
        config = load_system_config()

    service = EmbeddingService.from_config(config.embedding)
    client = _qdrant()
    dim = await service.dimension()
    _ensure_collection(client, dim)

    vault_root = Path(config.vault.root).expanduser()
    result = IndexResult()

    rows = session.execute(select(VaultNoteRecord)).scalars().all()
    for row in rows:
        if not force and row.indexed_hash == row.content_hash:
            result.notes_skipped += 1
            continue

        abs_path = vault_root / row.path
        try:
            raw = abs_path.read_text(encoding="utf-8")
        except OSError as e:
            result.errors.append(f"{row.path}: {e}")
            continue

        import frontmatter

        body_only = frontmatter.loads(raw).content
        chunks = chunk_text(body_only)

        _delete_note_points(client, row.note_id)

        if chunks:
            texts = [c.text for c in chunks]
            vectors = await service.encode(texts)
            points = [
                models.PointStruct(
                    id=_point_id(row.note_id, c.index),
                    vector=vectors[i],
                    payload=_payload(row, c.index, c.text),
                )
                for i, c in enumerate(chunks)
            ]
            client.upsert(collection_name=_COLLECTION, points=points)
            result.chunks_upserted += len(points)

        row.indexed_hash = row.content_hash
        result.notes_indexed += 1

    session.flush()
    return result


__all__ = ["IndexResult", "index_vault"]
