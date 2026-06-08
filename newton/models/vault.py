"""VaultNoteRecord — cached ACL + metadata for one vault note.

Schema mirrors ``migrations/006_vault.sql``. This is the SQLite cache row;
the parsed-in-memory representation is ``newton.vault.parser.VaultNote`` (a
different type on purpose — one is the on-disk parse result, this is the DB
cache). The scanner converts between them.

ACL list fields are JSON text (SQLite has no array type). Helpers expose
them as Python lists.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column

from newton.models.base import Base


class VaultNoteRecord(Base):
    """One cached note. ``path`` is unique, relative to the vault root."""

    __tablename__ = "vault_notes"

    note_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(unique=True)
    owner_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    read_users_json: Mapped[str] = mapped_column(default="[]", server_default="[]")
    read_personas_json: Mapped[str] = mapped_column(default="[]", server_default="[]")
    write_users_json: Mapped[str] = mapped_column(default="[]", server_default="[]")
    write_personas_json: Mapped[str] = mapped_column(default="[]", server_default="[]")
    status: Mapped[str] = mapped_column(
        default="pending_review", server_default="pending_review"
    )
    tags_json: Mapped[str] = mapped_column(default="[]", server_default="[]")
    content_hash: Mapped[str]
    mtime: Mapped[float] = mapped_column(default=0.0, server_default="0")
    indexed_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp()
    )

    # -- JSON convenience accessors -------------------------------------------

    @property
    def read_users(self) -> list[str]:
        return json.loads(self.read_users_json)

    @property
    def read_personas(self) -> list[str]:
        return json.loads(self.read_personas_json)

    @property
    def write_users(self) -> list[str]:
        return json.loads(self.write_users_json)

    @property
    def write_personas(self) -> list[str]:
        return json.loads(self.write_personas_json)

    @property
    def tags(self) -> list[str]:
        return json.loads(self.tags_json)

    def __repr__(self) -> str:
        return (
            f"<VaultNoteRecord #{self.note_id} {self.path!r} "
            f"owner={self.owner_user_id!r} status={self.status!r}>"
        )


__all__ = ["VaultNoteRecord"]
