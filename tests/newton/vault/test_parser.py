"""Tests for newton.vault.parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from newton.vault.parser import (
    ACL,
    ACLStatus,
    VaultParseError,
    parse,
    validate_against_db,
)

FIXTURES = Path(__file__).parent / "fixtures"


# -- structural parsing (no DB) ----------------------------------------------


def test_parse_full_acl():
    note = parse(FIXTURES / "full_acl.md")
    assert note.acl.owner == "sir"
    assert set(note.acl.read_users) == {"sir", "gf"}
    assert note.acl.read_personas == ["jarvis"]
    assert note.acl.write_users == ["sir"]
    assert note.acl.write_personas == []
    assert note.acl.status is ACLStatus.CANONICAL
    assert note.tags == ["project", "newton"]
    assert "Project Newton" in note.body
    assert len(note.content_hash) == 64  # sha256 hex


def test_parse_partial_acl_applies_defaults():
    note = parse(FIXTURES / "partial_acl.md")
    assert note.acl.owner == "gf"
    # read/write_users default to [owner]
    assert note.acl.read_users == ["gf"]
    assert note.acl.write_users == ["gf"]
    assert note.acl.read_personas == []
    assert note.acl.status is ACLStatus.SHARED
    assert note.tags == ["recipe"]


def test_parse_no_acl():
    note = parse(FIXTURES / "no_acl.md")
    assert note.acl.owner is None
    assert note.acl.status is ACLStatus.PENDING_REVIEW
    assert note.acl.read_users == []
    assert note.tags == []
    assert "Plain note" in note.body


def test_parse_malformed_frontmatter(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("---\nacl: [this, is, not, a, mapping\n---\nbody", encoding="utf-8")
    with pytest.raises(VaultParseError):
        parse(bad)


def test_parse_acl_not_a_mapping(tmp_path):
    bad = tmp_path / "bad2.md"
    bad.write_text("---\nacl: just-a-string\n---\nbody", encoding="utf-8")
    with pytest.raises(VaultParseError, match="must be a mapping"):
        parse(bad)


def test_parse_unreadable(tmp_path):
    with pytest.raises(VaultParseError, match="cannot read"):
        parse(tmp_path / "does-not-exist.md")


def test_unknown_acl_keys_preserved_not_rejected(tmp_path):
    note_path = tmp_path / "future.md"
    note_path.write_text(
        "---\nacl:\n  owner: sir\n  future_key: whatever\n  another: 123\n---\nbody",
        encoding="utf-8",
    )
    note = parse(note_path)
    assert note.acl.owner == "sir"
    assert note.acl.unknown_keys == ["another", "future_key"]


def test_owner_always_in_read_and_write():
    acl = ACL.from_frontmatter(
        {"owner": "sir", "read_users": ["gf"], "write_users": ["gf"]}
    )
    assert "sir" in acl.read_users
    assert "sir" in acl.write_users


def test_tags_as_scalar_coerced_to_list(tmp_path):
    note_path = tmp_path / "scalar_tag.md"
    note_path.write_text("---\ntags: single\n---\nbody", encoding="utf-8")
    note = parse(note_path)
    assert note.tags == ["single"]


def test_content_hash_changes_with_content(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("---\nacl:\n  owner: sir\n---\nbody one", encoding="utf-8")
    b.write_text("---\nacl:\n  owner: sir\n---\nbody two", encoding="utf-8")
    assert parse(a).content_hash != parse(b).content_hash


# -- DB referential validation ------------------------------------------------


def test_validate_against_db_all_known(seeded_db):
    from newton.db import get_session

    note = parse(FIXTURES / "full_acl.md")  # sir, gf, jarvis all seeded
    with get_session() as session:
        issues = validate_against_db(note, session)
    assert issues == []


def test_validate_against_db_unknown_user(seeded_db, tmp_path):
    from newton.db import get_session

    note_path = tmp_path / "ghost.md"
    note_path.write_text(
        "---\nacl:\n  owner: nobody\n  read_personas: [ghostpersona]\n---\nx",
        encoding="utf-8",
    )
    note = parse(note_path)
    with get_session() as session:
        issues = validate_against_db(note, session)
    problems = {(i.field, i.value) for i in issues}
    assert ("owner", "nobody") in problems
    assert ("read_personas", "ghostpersona") in problems
