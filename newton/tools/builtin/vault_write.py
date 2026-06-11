"""vault_write — save a note into the vault. Risk 2 (WRITE_LOCAL).

Writes are confined to the vault. A registered user may write under the
notes area (their own subtree) or the shared area; an unregistered caller
("guest") is forced into the quarantine directory regardless of the path
requested. After a successful write the note is scanned + re-indexed so it
becomes searchable immediately.

Default policy for risk 2 is require_approval, so dispatch routes this
through the approval hook before execute runs (the "save? share?" flow).
This tool therefore assumes approval already happened; it just writes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import frontmatter
from pydantic import BaseModel, Field

from newton.tools.base import RiskLevel, Tool, ToolContext, ToolResult
from newton.tools.builtin._paths import data_dir


class VaultWriteArgs(BaseModel):
    path: str = Field(
        ...,
        description=(
            "Path relative to the vault root, e.g. 'notes/sir/idea.md' or "
            "'shared/dinner.md'. Guests are redirected to quarantine."
        ),
    )
    content: str = Field(..., description="Markdown body of the note.")
    frontmatter: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional frontmatter mapping (acl, tags, ...).",
    )


class VaultWriteReturns(BaseModel):
    path: str  # final path written, relative to vault root
    quarantined: bool
    notes_indexed: int
    chunks_upserted: int


def _vault_root(context: ToolContext) -> Path:
    return data_dir(context) / "vault"


def _resolve_within(root: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``root``; raise ValueError if it escapes."""
    root_resolved = root.resolve()
    candidate = (root_resolved / relative).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError(f"path escapes vault: {relative!r} -> {candidate}")
    return candidate


def _is_registered_user(user_id: str) -> bool:
    from newton.db import get_session
    from newton.models import User

    with get_session() as session:
        return session.get(User, user_id) is not None


def _enforce_area(relative: str, user_id: str, config_layout) -> tuple[str, bool]:
    """Return (effective_relative_path, quarantined).

    Registered users may write under notes_dir/ or shared_dir/. Anyone else
    (guest) is redirected into quarantine_dir/, keeping the filename.
    """
    notes = config_layout.notes_dir
    shared = config_layout.shared_dir
    quarantine = config_layout.quarantine_dir

    rel = relative.lstrip("/")
    first = Path(rel).parts[0] if Path(rel).parts else ""

    if not _is_registered_user(user_id):
        # Guest: force into quarantine, keep just the basename to avoid
        # smuggling traversal via subdirs.
        return f"{quarantine}/{Path(rel).name}", True

    if first in (notes, shared):
        return rel, False

    # Registered user wrote outside the allowed areas -> put under their
    # own notes subtree.
    return f"{notes}/{user_id}/{Path(rel).name}", False


class VaultWriteTool(Tool):
    name = "vault_write"
    description = (
        "Save a markdown note into the vault. Registered users write to "
        "notes/ or shared/; guests are quarantined. Re-indexes on success."
    )
    risk = RiskLevel.WRITE_LOCAL
    args_schema = VaultWriteArgs
    returns_schema = VaultWriteReturns

    async def execute(self, args: VaultWriteArgs, context: ToolContext) -> ToolResult:
        from newton.db import get_session
        from newton.system_config import load_system_config
        from newton.vault.indexer import index_vault
        from newton.vault.scanner import scan

        config = load_system_config()
        root = _vault_root(context)

        # Decide the effective area (guest quarantine enforcement).
        try:
            effective_rel, quarantined = _enforce_area(
                args.path, context.user_id, config.vault.layout
            )
            target = _resolve_within(root, effective_rel)
        except ValueError as e:
            return ToolResult(status="denied", error=str(e))

        if target.suffix != ".md":
            return ToolResult(status="denied", error="vault notes must end in .md")

        # Compose the file with frontmatter (if any).
        post = frontmatter.Post(args.content, **args.frontmatter)
        rendered = frontmatter.dumps(post)

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")

        # Re-scan + re-index so the new note is searchable. The indexer reads
        # the vault root from config; point config at this context's root.
        config.vault.root = str(root)
        with get_session() as session:
            scan(session, config.vault)
            ir = await index_vault(session, config)
            # Best-effort biasing hook: harvest entities from the new note
            # into the writer's STT dictionary. Never breaks the save.
            from newton.vault.biasing_hook import on_vault_save

            bias_report = on_vault_save(session, args.content, context.user_id)

        rel_to_root = str(target.relative_to(root.resolve()))
        return ToolResult(
            status="ok",
            data={
                "path": rel_to_root,
                "quarantined": quarantined,
                "notes_indexed": ir.notes_indexed,
                "chunks_upserted": ir.chunks_upserted,
                "biasing": bias_report,
            },
        )


__all__ = ["VaultWriteTool"]
