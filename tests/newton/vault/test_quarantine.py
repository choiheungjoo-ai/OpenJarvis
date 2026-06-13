"""Tests for newton.vault.quarantine.

Marked qdrant+embedding: review() re-indexes via index_vault.
"""

from __future__ import annotations

import pytest

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


def _config(tmp_path):
    from newton.system_config import load_system_config

    config = load_system_config()
    config.vault.root = str(tmp_path / "vault")
    (tmp_path / "vault").mkdir(parents=True, exist_ok=True)
    return config


def _make_quarantine_file(config, name="2026-05-29-search.md", body="guest"):
    from pathlib import Path

    qdir = Path(config.vault.root) / config.vault.layout.quarantine_dir
    qdir.mkdir(parents=True, exist_ok=True)
    f = qdir / name
    f.write_text(f"# {name}\n\n{body}\n", encoding="utf-8")
    return f


def test_reconcile_registers_orphan_files(seeded_db, tmp_path):
    from newton.db import get_session
    from newton.vault.quarantine import reconcile

    config = _config(tmp_path)
    _make_quarantine_file(config)

    with get_session() as session:
        created = reconcile(session, config)
        assert len(created) == 1
        # Idempotent: second run creates nothing.
        assert reconcile(session, config) == []


def test_list_pending_includes_reconciled(seeded_db, tmp_path):
    from newton.db import get_session
    from newton.vault.quarantine import list_pending

    config = _config(tmp_path)
    _make_quarantine_file(config)

    with get_session() as session:
        items = list_pending(session, config)
    assert len(items) == 1
    assert items[0].path.endswith("2026-05-29-search.md")
    assert items[0].status == "pending_review"


@pytest.mark.asyncio
async def test_promote_moves_to_notes_and_marks(seeded_db, tmp_path, clean_collection):
    from pathlib import Path

    from newton.db import get_session
    from newton.models import GuestActivity
    from newton.vault.quarantine import Decision, list_pending, review

    config = _config(tmp_path)
    _make_quarantine_file(config)

    with get_session() as session:
        aid = list_pending(session, config)[0].activity_id
        report = await review(session, aid, Decision.PROMOTE, config, reviewed_by="sir")
        assert report["status"] == "promoted"
        assert report["path"].startswith("notes/sir/")

        row = session.get(GuestActivity, aid)
        assert row.status == "promoted"
        assert row.reviewed_by_user_id == "sir"
        assert row.reviewed_at is not None

    moved = Path(config.vault.root) / "notes" / "sir" / "2026-05-29-search.md"
    assert moved.exists()
    # No longer pending.
    with get_session() as session:
        assert list_pending(session, config) == []


@pytest.mark.asyncio
async def test_shared_moves_to_shared(seeded_db, tmp_path, clean_collection):
    from pathlib import Path

    from newton.db import get_session
    from newton.vault.quarantine import Decision, list_pending, review

    config = _config(tmp_path)
    _make_quarantine_file(config)
    with get_session() as session:
        aid = list_pending(session, config)[0].activity_id
        report = await review(session, aid, Decision.SHARED, config, reviewed_by="sir")
        assert report["status"] == "promoted"
        assert report["path"].startswith("shared/")
    assert (Path(config.vault.root) / "shared" / "2026-05-29-search.md").exists()


@pytest.mark.asyncio
async def test_reject_deletes_file(seeded_db, tmp_path, clean_collection):
    from newton.db import get_session
    from newton.models import GuestActivity
    from newton.vault.quarantine import Decision, list_pending, review

    config = _config(tmp_path)
    f = _make_quarantine_file(config)
    with get_session() as session:
        aid = list_pending(session, config)[0].activity_id
        report = await review(session, aid, Decision.REJECT, config, reviewed_by="sir")
        assert report["status"] == "rejected"
        assert session.get(GuestActivity, aid).status == "rejected"
    assert not f.exists()


@pytest.mark.asyncio
async def test_hold_keeps_pending(seeded_db, tmp_path, clean_collection):
    from newton.db import get_session
    from newton.vault.quarantine import Decision, list_pending, review

    config = _config(tmp_path)
    _make_quarantine_file(config)
    with get_session() as session:
        aid = list_pending(session, config)[0].activity_id
        report = await review(session, aid, Decision.HOLD, config, reviewed_by="sir")
        assert report["status"] == "pending_review"
        # Still listed.
        assert len(list_pending(session, config)) == 1


@pytest.mark.asyncio
async def test_review_unknown_id_raises(seeded_db, tmp_path, clean_collection):
    from newton.db import get_session
    from newton.vault.quarantine import Decision, review

    config = _config(tmp_path)
    with get_session() as session:
        with pytest.raises(ValueError):
            await review(session, 9999, Decision.PROMOTE, config)
