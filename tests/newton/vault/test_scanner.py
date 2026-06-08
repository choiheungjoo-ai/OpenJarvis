"""Tests for newton.vault.scanner."""

from __future__ import annotations

from newton.system_config import VaultConfig


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _cfg(root) -> VaultConfig:
    return VaultConfig(root=str(root))


def _note(owner="sir", status="canonical", body="hello"):
    return f"---\nacl:\n  owner: {owner}\n  status: {status}\ntags: [t1]\n---\n{body}\n"


# -- empty / basic ------------------------------------------------------------


def test_scan_empty_vault(seeded_db, tmp_path):
    from newton.db import get_session
    from newton.vault.scanner import scan

    with get_session() as session:
        result = scan(session, _cfg(tmp_path))
    assert result.scanned == 0
    assert result.added == 0


def test_scan_three_notes(seeded_db, tmp_path):
    from sqlalchemy import func, select

    from newton.db import get_session
    from newton.models.vault import VaultNoteRecord
    from newton.vault.scanner import scan

    _write(tmp_path / "notes" / "a.md", _note())
    _write(tmp_path / "notes" / "b.md", _note(body="second"))
    _write(tmp_path / "shared" / "c.md", _note(owner="gf", status="shared"))

    with get_session() as session:
        result = scan(session, _cfg(tmp_path))
        count = session.execute(
            select(func.count()).select_from(VaultNoteRecord)
        ).scalar_one()

    assert result.scanned == 3
    assert result.added == 3
    assert count == 3


# -- incremental --------------------------------------------------------------


def test_rescan_unchanged_is_noop(seeded_db, tmp_path):
    from newton.db import get_session
    from newton.vault.scanner import scan

    _write(tmp_path / "notes" / "a.md", _note())
    with get_session() as session:
        scan(session, _cfg(tmp_path))
    with get_session() as session:
        result = scan(session, _cfg(tmp_path))
    assert result.added == 0
    assert result.unchanged == 1
    assert result.updated == 0


def test_modify_note_updates_only_that_row(seeded_db, tmp_path):
    import os
    import time

    from sqlalchemy import select

    from newton.db import get_session
    from newton.models.vault import VaultNoteRecord
    from newton.vault.scanner import scan

    a = tmp_path / "notes" / "a.md"
    b = tmp_path / "notes" / "b.md"
    _write(a, _note(body="original"))
    _write(b, _note(body="b stays"))
    with get_session() as session:
        scan(session, _cfg(tmp_path))

    # Modify a's content + bump mtime to ensure detection.
    time.sleep(0.01)
    _write(a, _note(body="CHANGED"))
    os.utime(a, None)

    with get_session() as session:
        result = scan(session, _cfg(tmp_path))
        rows = {
            r.path: r for r in session.execute(select(VaultNoteRecord)).scalars().all()
        }

    assert result.updated == 1
    assert result.unchanged == 1
    assert "CHANGED" not in rows["notes/a.md"].content_hash  # hash, not body
    # b unchanged
    assert rows["notes/b.md"].status == "canonical"


def test_prune_removes_deleted_files(seeded_db, tmp_path):
    from sqlalchemy import func, select

    from newton.db import get_session
    from newton.models.vault import VaultNoteRecord
    from newton.vault.scanner import scan

    a = tmp_path / "notes" / "a.md"
    _write(a, _note())
    _write(tmp_path / "notes" / "b.md", _note(body="b"))
    with get_session() as session:
        scan(session, _cfg(tmp_path))

    a.unlink()
    with get_session() as session:
        result = scan(session, _cfg(tmp_path))
        count = session.execute(
            select(func.count()).select_from(VaultNoteRecord)
        ).scalar_one()

    assert result.removed == 1
    assert count == 1


# -- owner inference ----------------------------------------------------------


def test_owner_inferred_from_path(seeded_db, tmp_path):
    from sqlalchemy import select

    from newton.db import get_session
    from newton.models.vault import VaultNoteRecord
    from newton.vault.scanner import scan

    # No acl block; owner should come from notes/<user>/...
    _write(tmp_path / "notes" / "sir" / "diary.md", "# no frontmatter\nbody")
    with get_session() as session:
        scan(session, _cfg(tmp_path))
        row = session.execute(select(VaultNoteRecord)).scalar_one()
    assert row.owner_user_id == "sir"
    assert row.status == "canonical"


def test_quarantine_dir_marks_pending(seeded_db, tmp_path):
    from sqlalchemy import select

    from newton.db import get_session
    from newton.models.vault import VaultNoteRecord
    from newton.vault.scanner import scan

    _write(tmp_path / "_guest_quarantine" / "x.md", _note(status="canonical"))
    with get_session() as session:
        scan(session, _cfg(tmp_path))
        row = session.execute(select(VaultNoteRecord)).scalar_one()
    assert row.status == "pending_review"


def test_no_owner_no_path_is_pending(seeded_db, tmp_path):
    from sqlalchemy import select

    from newton.db import get_session
    from newton.models.vault import VaultNoteRecord
    from newton.vault.scanner import scan

    # bare file under notes/, no acl, no user subdir -> no owner
    _write(tmp_path / "notes" / "orphan.md", "# orphan\nno acl")
    with get_session() as session:
        scan(session, _cfg(tmp_path))
        row = session.execute(select(VaultNoteRecord)).scalar_one()
    assert row.owner_user_id is None
    assert row.status == "pending_review"
