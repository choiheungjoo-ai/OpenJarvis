"""ACL-filtered search tests. Require live Qdrant + TEI.

Verifies option-C access semantics:
  - owner sees own note
  - a user not in read_users (and not owner) does not
  - persona restriction: empty read_personas -> any persona; explicit list
    -> only those personas
  - status filter excludes pending_review / shared by default
"""

from __future__ import annotations

import pytest

from newton.system_config import SystemConfig, VaultConfig

pytestmark = [pytest.mark.qdrant, pytest.mark.embedding]

_COLLECTION = "vault"


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _config(root) -> SystemConfig:
    cfg = SystemConfig()
    cfg.vault = VaultConfig(root=str(root))
    return cfg


def _note(owner, *, read_users=None, read_personas=None, status="canonical", body):
    lines = ["---", "acl:", f"  owner: {owner}", f"  status: {status}"]
    if read_users is not None:
        lines.append(f"  read_users: [{', '.join(read_users)}]")
    if read_personas is not None:
        lines.append(f"  read_personas: [{', '.join(read_personas)}]")
    lines += ["---", "", body, ""]
    return "\n".join(lines)


@pytest.fixture
def clean_collection():
    from newton.vault.qdrant_client import get_client

    client = get_client()
    if client.collection_exists(_COLLECTION):
        client.delete_collection(_COLLECTION)
    yield client
    if client.collection_exists(_COLLECTION):
        client.delete_collection(_COLLECTION)


async def _index(cfg):
    from newton.db import get_session
    from newton.vault.indexer import index_vault
    from newton.vault.scanner import scan

    with get_session() as session:
        scan(session, cfg.vault)
        await index_vault(session, cfg)


@pytest.mark.asyncio
async def test_owner_sees_own_note(seeded_db, tmp_path, clean_collection):
    from newton.vault.search import search

    cfg = _config(tmp_path)
    _write(
        tmp_path / "notes" / "sir" / "secret.md",
        _note("sir", read_users=["sir"], body="The launch code is hunter2."),
    )
    await _index(cfg)

    hits = await search("launch code", "sir", "jarvis", config=cfg)
    assert len(hits) >= 1
    assert any("launch code".split()[0] in h.text.lower() for h in hits)


@pytest.mark.asyncio
async def test_non_grantee_blocked(seeded_db, tmp_path, clean_collection):
    from newton.vault.search import search

    cfg = _config(tmp_path)
    _write(
        tmp_path / "notes" / "sir" / "secret.md",
        _note("sir", read_users=["sir"], body="The launch code is hunter2."),
    )
    await _index(cfg)

    # gf is not in read_users and is not the owner -> no hits.
    hits = await search("launch code", "gf", "friday", config=cfg)
    assert hits == []


@pytest.mark.asyncio
async def test_shared_note_visible_to_listed_user(
    seeded_db, tmp_path, clean_collection
):
    from newton.vault.search import search

    cfg = _config(tmp_path)
    _write(
        tmp_path / "notes" / "sir" / "shared.md",
        _note(
            "sir",
            read_users=["sir", "gf"],
            body="Dinner reservation at eight tonight.",
        ),
    )
    await _index(cfg)

    hits = await search("dinner reservation", "gf", "friday", config=cfg)
    assert len(hits) >= 1


@pytest.mark.asyncio
async def test_persona_restriction(seeded_db, tmp_path, clean_collection):
    from newton.vault.search import search

    cfg = _config(tmp_path)
    # read_personas: [jarvis] -> friday must NOT see it even though gf can read.
    _write(
        tmp_path / "notes" / "sir" / "jarvis_only.md",
        _note(
            "sir",
            read_users=["sir", "gf"],
            read_personas=["jarvis"],
            body="Project Glasswing briefing notes.",
        ),
    )
    await _index(cfg)

    via_jarvis = await search("glasswing briefing", "sir", "jarvis", config=cfg)
    via_friday = await search("glasswing briefing", "gf", "friday", config=cfg)
    assert len(via_jarvis) >= 1
    assert via_friday == []


@pytest.mark.asyncio
async def test_empty_personas_any_persona(seeded_db, tmp_path, clean_collection):
    from newton.vault.search import search

    cfg = _config(tmp_path)
    # No read_personas -> normalised to ["*"] -> any persona may see it.
    _write(
        tmp_path / "notes" / "sir" / "open.md",
        _note("sir", read_users=["sir"], body="Grocery list: milk and eggs."),
    )
    await _index(cfg)

    via_jarvis = await search("grocery list", "sir", "jarvis", config=cfg)
    via_butler = await search("grocery list", "sir", "butler", config=cfg)
    assert len(via_jarvis) >= 1
    assert len(via_butler) >= 1


@pytest.mark.asyncio
async def test_status_filter_excludes_pending(seeded_db, tmp_path, clean_collection):
    from newton.vault.search import search

    cfg = _config(tmp_path)
    # Quarantined note -> status pending_review; default search excludes it.
    _write(
        tmp_path / "_guest_quarantine" / "g.md",
        _note("sir", read_users=["sir"], body="Quarantined guest content here."),
    )
    await _index(cfg)

    default = await search("quarantined guest", "sir", "jarvis", config=cfg)
    explicit = await search(
        "quarantined guest",
        "sir",
        "jarvis",
        status_filter="pending_review",
        config=cfg,
    )
    assert default == []
    assert len(explicit) >= 1


@pytest.mark.asyncio
async def test_search_empty_collection(seeded_db, tmp_path, clean_collection):
    from newton.vault.search import search

    cfg = _config(tmp_path)
    hits = await search("anything", "sir", "jarvis", config=cfg)
    assert hits == []
