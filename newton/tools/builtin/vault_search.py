"""vault_search — semantic search over the vault. Risk 1 (READ_LOCAL).

Wraps newton.vault.search.search, passing the caller's identity from the
ToolContext so ACL filtering applies: a persona only sees what (user_id,
persona_id) is allowed to read. Read-only; default policy auto_allow.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from newton.tools.base import RiskLevel, Tool, ToolContext, ToolResult


class VaultSearchArgs(BaseModel):
    query: str = Field(..., description="Natural-language search query.")
    limit: int = Field(default=5, ge=1, le=50, description="Max results.")
    status_filter: str = Field(
        default="canonical",
        description="Only notes with this status (canonical|shared|pending_review).",
    )


class VaultSearchReturns(BaseModel):
    hits: list[dict[str, Any]]
    count: int


class VaultSearchTool(Tool):
    name = "vault_search"
    description = (
        "Semantic search over the user's vault notes, filtered by who is "
        "asking and which persona is active. Returns matching chunks."
    )
    risk = RiskLevel.READ_LOCAL
    args_schema = VaultSearchArgs
    returns_schema = VaultSearchReturns

    async def execute(self, args: VaultSearchArgs, context: ToolContext) -> ToolResult:
        from newton.vault.search import search

        try:
            hits = await search(
                args.query,
                context.user_id,
                context.persona_id,
                limit=args.limit,
                status_filter=args.status_filter,
            )
        except Exception as e:  # noqa: BLE001
            return ToolResult(status="error", error=f"{type(e).__name__}: {e}")

        payload = [
            {
                "note_id": h.note_id,
                "chunk_index": h.chunk_index,
                "path": h.path,
                "score": h.score,
                "text": h.text,
                "owner_user_id": h.owner_user_id,
                "status": h.status,
                "tags": h.tags,
            }
            for h in hits
        ]
        return ToolResult(status="ok", data={"hits": payload, "count": len(payload)})


__all__ = ["VaultSearchTool"]
