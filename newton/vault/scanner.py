"""Vault scanner.

Walks the vault directory, parses each ``.md`` note, and upserts a cache row
into ``vault_notes``. Incremental: a note whose mtime is unchanged is skipped;
if mtime changed but the content hash is identical (a touch), only timestamps
update.

Owner resolution, in priority order:
    1. ``acl.owner`` from the note's frontmatter
    2. path inference: ``<notes_dir>/<user_id>/...`` -> owner = <user_id>
    3. otherwise: no owner; the note is marked pending_review (quarantined
       from RAG until promoted)

Layout is configurable (newton.yaml ``vault`` section), not hardcoded, so the
directory conventions can change without touching this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from newton.system_config import VaultConfig, load_system_config
from newton.vault.parser import ACLStatus, VaultNote, VaultParseError, parse


@dataclass
class ScanResult:
    """Summary of one scan pass."""

    scanned: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    skipped: list[str] = field(default_factory=list)  # paths skipped + reason


def _vault_root(config: VaultConfig) -> Path:
    return Path(config.root).expanduser()


def _infer_owner_from_path(rel_path: Path, config: VaultConfig) -> str | None:
    """Infer owner from a path like ``<notes_dir>/<user_id>/...``.

    Returns the user_id segment if the note sits under notes_dir in a
    per-user subdirectory, else None.
    """
    parts = rel_path.parts
    if len(parts) >= 2 and parts[0] == config.layout.notes_dir:
        candidate = parts[1]
        # A bare file directly under notes_dir (no user subdir) has no owner.
        if candidate and not candidate.endswith(".md"):
            return candidate
    return None


def _is_quarantined(rel_path: Path, config: VaultConfig) -> bool:
    return rel_path.parts and rel_path.parts[0] == config.layout.quarantine_dir


def _resolve_owner_and_status(
    note: VaultNote, rel_path: Path, config: VaultConfig
) -> tuple[str | None, str]:
    """Return (owner_user_id, status) after applying inference rules."""
    if _is_quarantined(rel_path, config):
        return note.acl.owner, ACLStatus.PENDING_REVIEW.value

    owner = note.acl.owner or _infer_owner_from_path(rel_path, config)
    if owner is None:
        return None, ACLStatus.PENDING_REVIEW.value

    # An owned note with no explicit status is canonical. This covers both
    # path-inferred owners and frontmatter owners that omitted `status`
    # (the ACL default is pending_review, which would otherwise hide the
    # note from canonical search).
    if note.acl.status_explicit:
        status = note.acl.status.value
    else:
        status = ACLStatus.CANONICAL.value
    return owner, status


def _row_values(
    note: VaultNote, rel_path: Path, owner: str | None, status: str, mtime: float
) -> dict[str, Any]:
    acl = note.acl
    return {
        "path": str(rel_path),
        "owner_user_id": owner,
        "read_users_json": json.dumps(acl.read_users),
        "read_personas_json": json.dumps(acl.read_personas),
        "write_users_json": json.dumps(acl.write_users),
        "write_personas_json": json.dumps(acl.write_personas),
        "status": status,
        "tags_json": json.dumps(note.tags),
        "content_hash": note.content_hash,
        "mtime": mtime,
    }


def scan(
    session: Any,
    config: VaultConfig | None = None,
    *,
    prune: bool = True,
) -> ScanResult:
    """Scan the vault and upsert cache rows. Returns a ScanResult.

    ``prune`` removes cache rows whose files no longer exist.
    """
    from sqlalchemy import select

    from newton.models.vault import VaultNoteRecord

    if config is None:
        config = load_system_config().vault

    root = _vault_root(config)
    result = ScanResult()

    existing: dict[str, VaultNoteRecord] = {
        r.path: r for r in session.execute(select(VaultNoteRecord)).scalars().all()
    }
    seen: set[str] = set()

    if root.exists():
        for abs_path in sorted(root.rglob("*.md")):
            rel_path = abs_path.relative_to(root)
            rel_str = str(rel_path)
            seen.add(rel_str)
            result.scanned += 1

            try:
                mtime = abs_path.stat().st_mtime
            except OSError:
                result.skipped.append(f"{rel_str}: stat failed")
                continue

            row = existing.get(rel_str)
            if row is not None and row.mtime == mtime:
                result.unchanged += 1
                continue

            try:
                note = parse(abs_path)
            except VaultParseError as e:
                result.skipped.append(f"{rel_str}: {e}")
                continue

            owner, status = _resolve_owner_and_status(note, rel_path, config)
            values = _row_values(note, rel_path, owner, status, mtime)

            if row is None:
                session.add(VaultNoteRecord(**values))
                result.added += 1
            elif row.content_hash == note.content_hash:
                # touch only: refresh mtime, leave the rest.
                row.mtime = mtime
                result.unchanged += 1
            else:
                for k, v in values.items():
                    setattr(row, k, v)
                result.updated += 1

    if prune:
        for path_str, row in existing.items():
            if path_str not in seen:
                session.delete(row)
                result.removed += 1

    session.flush()
    return result


__all__ = ["ScanResult", "scan"]
