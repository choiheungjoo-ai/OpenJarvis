"""Guest quarantine review workflow.

Guest activity lands as a note under ``_guest_quarantine/`` *and* a
``GuestActivity`` row (status ``pending_review``). sir reviews each item
and decides: promote to the canonical vault, move to shared, reject
(delete), or hold (leave pending).

Design choice (stability + scale): the ``GuestActivity`` row is the source
of truth — reviews are keyed by ``activity_id`` (a primary key, never
ambiguous), and every decision is recorded (status, reviewed_at,
reviewed_by). Files reached the quarantine without a row (e.g. created out
of band) are first folded in by :func:`reconcile`, which creates the
missing rows, so review always operates on a real record.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Decision(str, enum.Enum):
    PROMOTE = "promote"  # -> notes/   (canonical, owned by reviewer)
    SHARED = "shared"  # -> shared/   (shared area)
    REJECT = "reject"  # delete file, mark rejected
    HOLD = "hold"  # leave in quarantine, stay pending


@dataclass
class QuarantineItem:
    activity_id: int
    path: str  # relative to vault root
    activity_type: str | None
    summary: str | None
    status: str
    created_at: datetime | None


def _quarantine_root(config: Any) -> Path:
    return Path(config.vault.root) / config.vault.layout.quarantine_dir


def _rel_to_vault(config: Any, p: Path) -> str:
    return str(p.relative_to(Path(config.vault.root)))


def reconcile(session: Any, config: Any) -> list[int]:
    """Register quarantine files that have no GuestActivity row.

    Returns the activity_ids created. Idempotent: a file already pointed to
    by some row is left alone. This is what lets an out-of-band file (the
    doc's ``echo > _guest_quarantine/...`` case) become reviewable.
    """
    from sqlalchemy import select

    from newton.models import GuestActivity

    qroot = _quarantine_root(config)
    if not qroot.exists():
        return []

    known = {
        row.raw_content_path
        for row in session.execute(
            select(GuestActivity).where(GuestActivity.raw_content_path.is_not(None))
        ).scalars()
    }

    created: list[int] = []
    for f in sorted(qroot.rglob("*.md")):
        rel = _rel_to_vault(config, f)
        if rel in known:
            continue
        row = GuestActivity(
            activity_type="learning",
            summary=f"Quarantined file {f.name}",
            raw_content_path=rel,
            status="pending_review",
        )
        session.add(row)
        session.flush()
        created.append(row.activity_id)
    return created


def list_pending(session: Any, config: Any) -> list[QuarantineItem]:
    """All pending guest activity, after reconciling orphan files."""
    from sqlalchemy import select

    from newton.models import GuestActivity

    reconcile(session, config)
    rows = (
        session.execute(
            select(GuestActivity)
            .where(GuestActivity.status == "pending_review")
            .order_by(GuestActivity.created_at)
        )
        .scalars()
        .all()
    )
    return [
        QuarantineItem(
            activity_id=r.activity_id,
            path=r.raw_content_path or "",
            activity_type=r.activity_type,
            summary=r.summary,
            status=r.status,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def review(
    session: Any,
    activity_id: int,
    decision: Decision,
    config: Any,
    *,
    reviewed_by: str | None = None,
    target_owner: str | None = None,
) -> dict[str, Any]:
    """Apply a review decision to one quarantined item.

    Moves/deletes the file, updates the GuestActivity status, records who
    reviewed it, and re-indexes the vault so search reflects the change.
    Returns a small report. Raises ValueError on an unknown id.
    """
    from newton.models import GuestActivity
    from newton.vault.indexer import index_vault
    from newton.vault.scanner import scan

    row = session.get(GuestActivity, activity_id)
    if row is None:
        raise ValueError(f"unknown activity_id {activity_id}")

    vault_root = Path(config.vault.root)
    layout = config.vault.layout
    src = (vault_root / row.raw_content_path) if row.raw_content_path else None

    new_status = row.status
    dest_rel: str | None = None

    if decision is Decision.HOLD:
        new_status = "pending_review"

    elif decision is Decision.REJECT:
        if src and src.exists():
            src.unlink()
        new_status = "rejected"

    elif decision in (Decision.PROMOTE, Decision.SHARED):
        if not (src and src.exists()):
            raise ValueError(f"quarantine file missing for #{activity_id}")
        if decision is Decision.PROMOTE:
            owner = target_owner or reviewed_by or "sir"
            dest = vault_root / layout.notes_dir / owner / src.name
        else:
            dest = vault_root / layout.shared_dir / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dest)
        dest_rel = str(dest.relative_to(vault_root))
        row.raw_content_path = dest_rel
        new_status = "promoted"

    row.status = new_status
    if decision is not Decision.HOLD:
        row.reviewed_at = datetime.now(timezone.utc)
        row.reviewed_by_user_id = reviewed_by
    session.flush()

    # Re-index so the moved/removed note is reflected in search.
    scan(session, config.vault)
    await index_vault(session, config)

    return {
        "activity_id": activity_id,
        "decision": decision.value,
        "status": new_status,
        "path": dest_rel or (row.raw_content_path or ""),
    }


__all__ = [
    "Decision",
    "QuarantineItem",
    "list_pending",
    "reconcile",
    "review",
]
