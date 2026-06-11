"""Tests for vault_search / vault_write tools.

Require live Qdrant + TEI (the tools call real search/index).
"""

from __future__ import annotations

import pytest

from newton.tools.base import ToolContext

pytestmark = [pytest.mark.qdrant, pytest.mark.embedding]

_COLLECTION = "vault"


@pytest.fixture
def clean_collection():
    from newton.vault.qdrant_client import get_client

    client = get_client()
    if client.collection_exists(_COLLECTION):
        client.delete_collection(_COLLECTION)
    yield client
    if client.collection_exists(_COLLECTION):
        client.delete_collection(_COLLECTION)


def _ctx(user_id="sir", persona_id="jarvis", data_dir=None, auto_approve=True):
    extra = {"data_dir": str(data_dir)} if data_dir else {}
    return ToolContext(
        user_id=user_id,
        persona_id=persona_id,
        auto_approve=auto_approve,
        extra=extra,
    )


# -- vault_write --------------------------------------------------------------


@pytest.mark.asyncio
async def test_vault_write_saves_and_indexes(seeded_db, tmp_path, clean_collection):
    from newton.tools.builtin.vault_write import VaultWriteArgs, VaultWriteTool

    tool = VaultWriteTool()
    args = VaultWriteArgs(
        path="notes/sir/idea.md",
        content="# Idea\n\nBuild a better mousetrap.",
        frontmatter={"acl": {"owner": "sir"}},
    )
    result = await tool.execute(args, _ctx(data_dir=tmp_path))

    assert result.status == "ok"
    assert result.data["path"] == "notes/sir/idea.md"
    assert result.data["quarantined"] is False
    assert result.data["notes_indexed"] >= 1
    # File exists on disk.
    assert (tmp_path / "vault" / "notes" / "sir" / "idea.md").exists()


@pytest.mark.asyncio
async def test_vault_write_then_search_finds_it(seeded_db, tmp_path, clean_collection):
    from newton.tools.builtin.vault_search import VaultSearchArgs, VaultSearchTool
    from newton.tools.builtin.vault_write import VaultWriteArgs, VaultWriteTool

    ctx = _ctx(data_dir=tmp_path)
    await VaultWriteTool().execute(
        VaultWriteArgs(
            path="notes/sir/pizza.md",
            content="# Dinner\n\nThe pizza recipe uses fresh basil.",
            frontmatter={"acl": {"owner": "sir"}},
        ),
        ctx,
    )

    hits = await VaultSearchTool().execute(VaultSearchArgs(query="pizza recipe"), ctx)
    assert hits.status == "ok"
    assert hits.data["count"] >= 1


@pytest.mark.asyncio
async def test_vault_write_guest_quarantined(seeded_db, tmp_path, clean_collection):
    from newton.tools.builtin.vault_write import VaultWriteArgs, VaultWriteTool

    # "visitor" is not a seeded user -> guest -> forced to quarantine.
    ctx = _ctx(user_id="visitor", persona_id="butler", data_dir=tmp_path)
    result = await VaultWriteTool().execute(
        VaultWriteArgs(
            path="notes/sir/secret.md",  # tries to write into sir's area
            content="# Sneaky\n\nshould be quarantined",
        ),
        ctx,
    )
    assert result.status == "ok"
    assert result.data["quarantined"] is True
    assert result.data["path"].startswith("_guest_quarantine/")
    # It did NOT land in sir's area.
    assert not (tmp_path / "vault" / "notes" / "sir" / "secret.md").exists()


@pytest.mark.asyncio
async def test_vault_write_rejects_non_md(seeded_db, tmp_path, clean_collection):
    from newton.tools.builtin.vault_write import VaultWriteArgs, VaultWriteTool

    result = await VaultWriteTool().execute(
        VaultWriteArgs(path="notes/sir/data.txt", content="x"),
        _ctx(data_dir=tmp_path),
    )
    assert result.status == "denied"
    assert ".md" in result.error


@pytest.mark.asyncio
async def test_vault_write_path_escape_denied(seeded_db, tmp_path, clean_collection):
    from newton.tools.builtin.vault_write import VaultWriteArgs, VaultWriteTool

    result = await VaultWriteTool().execute(
        VaultWriteArgs(path="../../etc/evil.md", content="x"),
        _ctx(data_dir=tmp_path),
    )
    # Registered user: escaping path gets redirected under notes/<user>/ by
    # basename, so it stays in the vault (no escape). Confirm it's contained.
    assert result.status == "ok"
    assert result.data["path"].startswith("notes/sir/")


# -- vault_search via dispatch (approval gating) ------------------------------


@pytest.mark.asyncio
async def test_search_tool_auto_allow_via_dispatch(
    seeded_db, tmp_path, clean_collection
):
    from newton.tools.assembly import build_tool_registry
    from newton.tools.builtin.vault_write import VaultWriteArgs, VaultWriteTool

    ctx = _ctx(data_dir=tmp_path)
    await VaultWriteTool().execute(
        VaultWriteArgs(
            path="notes/sir/note.md",
            content="# Note\n\nNewton architecture overview.",
            frontmatter={"acl": {"owner": "sir"}},
        ),
        ctx,
    )

    registry = build_tool_registry(auto_approve=True)
    result = await registry.dispatch("vault_search", {"query": "architecture"}, ctx)
    assert result.status == "ok"
    assert result.data["count"] >= 1


@pytest.mark.asyncio
async def test_write_tool_gated_by_policy(seeded_db, tmp_path, clean_collection):
    """risk 2 vault_write goes through approval; auto_approve lets it run."""
    from newton.tools.assembly import build_tool_registry

    ctx = _ctx(data_dir=tmp_path)
    registry = build_tool_registry(auto_approve=True)
    result = await registry.dispatch(
        "vault_write",
        {
            "path": "notes/sir/viadispatch.md",
            "content": "# Via\n\nthrough dispatch",
            "frontmatter": {"acl": {"owner": "sir"}},
        },
        ctx,
    )
    assert result.status == "ok"
    assert (tmp_path / "vault" / "notes" / "sir" / "viadispatch.md").exists()
