"""Indexer tests. Require live Qdrant AND TEI.

    scripts/newton/qdrant-up.sh
    scripts/newton/tei-up.sh

Marked both ``qdrant`` and ``embedding`` so they're skipped unless both
services are expected.
"""

from __future__ import annotations

import pytest

from newton.system_config import SystemConfig, VaultConfig

pytestmark = [pytest.mark.qdrant, pytest.mark.embedding]

_COLLECTION = "vault"


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _note(owner="sir", status="canonical", body="First section.\n\n## Arch\n\nSecond."):
    return f"---\nacl:\n  owner: {owner}\n  status: {status}\n---\n# Title\n\n{body}\n"


def _config(root) -> SystemConfig:
    cfg = SystemConfig()
    cfg.vault = VaultConfig(root=str(root))
    return cfg


def _count_points(client, note_id=None):
    from qdrant_client import models

    flt = None
    if note_id is not None:
        flt = models.Filter(
            must=[
                models.FieldCondition(
                    key="note_id", match=models.MatchValue(value=note_id)
                )
            ]
        )
    return client.count(collection_name=_COLLECTION, count_filter=flt).count


@pytest.fixture
def clean_collection():
    """Drop the vault collection before each test for isolation."""
    from newton.vault.qdrant_client import get_client

    client = get_client()
    if client.collection_exists(_COLLECTION):
        client.delete_collection(_COLLECTION)
    yield client
    if client.collection_exists(_COLLECTION):
        client.delete_collection(_COLLECTION)


@pytest.mark.asyncio
async def test_index_one_note_two_chunks(seeded_db, tmp_path, clean_collection):
    from newton.db import get_session
    from newton.vault.indexer import index_vault
    from newton.vault.scanner import scan

    cfg = _config(tmp_path)
    _write(tmp_path / "notes" / "sir" / "sample.md", _note())

    with get_session() as session:
        scan(session, cfg.vault)
        result = await index_vault(session, cfg)

    assert result.notes_indexed == 1
    # "# Title\n\nFirst section." + "## Arch\n\nSecond." -> 2 chunks
    assert result.chunks_upserted == 2
    assert _count_points(clean_collection) == 2


@pytest.mark.asyncio
async def test_reindex_idempotent(seeded_db, tmp_path, clean_collection):
    from newton.db import get_session
    from newton.vault.indexer import index_vault
    from newton.vault.scanner import scan

    cfg = _config(tmp_path)
    _write(tmp_path / "notes" / "sir" / "a.md", _note())

    with get_session() as session:
        scan(session, cfg.vault)
        await index_vault(session, cfg)
    with get_session() as session:
        scan(session, cfg.vault)
        result = await index_vault(session, cfg)

    assert result.notes_indexed == 0
    assert result.notes_skipped == 1


@pytest.mark.asyncio
async def test_reindex_on_content_change(seeded_db, tmp_path, clean_collection):
    import os
    import time

    from newton.db import get_session
    from newton.vault.indexer import index_vault
    from newton.vault.scanner import scan

    cfg = _config(tmp_path)
    note = tmp_path / "notes" / "sir" / "a.md"
    _write(note, _note())
    with get_session() as session:
        scan(session, cfg.vault)
        await index_vault(session, cfg)

    time.sleep(0.01)
    _write(note, _note(body="Changed.\n\n## New\n\nThird section here."))
    os.utime(note, None)

    with get_session() as session:
        scan(session, cfg.vault)
        result = await index_vault(session, cfg)

    assert result.notes_indexed == 1


@pytest.mark.asyncio
async def test_shrink_leaves_no_orphans(seeded_db, tmp_path, clean_collection):
    import os
    import time

    from newton.db import get_session
    from newton.vault.indexer import index_vault
    from newton.vault.scanner import scan

    cfg = _config(tmp_path)
    note = tmp_path / "notes" / "sir" / "a.md"
    # 3 sections -> 3 chunks
    _write(note, _note(body="One.\n\n## Two\n\nt\n\n## Three\n\nth"))
    with get_session() as session:
        scan(session, cfg.vault)
        r1 = await index_vault(session, cfg)
    assert r1.chunks_upserted == 3

    # shrink to 1 section
    time.sleep(0.01)
    _write(note, _note(body="Only one section now."))
    os.utime(note, None)
    with get_session() as session:
        scan(session, cfg.vault)
        await index_vault(session, cfg)

    # Total points must reflect only the new chunks (no orphans from the 3).
    assert _count_points(clean_collection) == 1


@pytest.mark.asyncio
async def test_force_reindexes_all(seeded_db, tmp_path, clean_collection):
    from newton.db import get_session
    from newton.vault.indexer import index_vault
    from newton.vault.scanner import scan

    cfg = _config(tmp_path)
    _write(tmp_path / "notes" / "sir" / "a.md", _note())
    with get_session() as session:
        scan(session, cfg.vault)
        await index_vault(session, cfg)
    with get_session() as session:
        result = await index_vault(session, cfg, force=True)
    assert result.notes_indexed == 1  # forced despite unchanged hash
