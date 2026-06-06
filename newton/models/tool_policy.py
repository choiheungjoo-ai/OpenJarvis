"""ToolPolicy — per (tool, persona, user) approval override.

Schema mirrors ``migrations/002_tool_policies.sql``.  A NULL ``persona_id``
or ``user_id`` is a wildcard ("any").  Resolution and the risk-based default
live in ``newton/tools/policy.py``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from newton.models.base import Base


class ToolPolicy(Base):
    """One approval-policy row.  Most specific matching row wins at lookup."""

    __tablename__ = "tool_policies"
    __table_args__ = (
        CheckConstraint("require_approval IN (0,1)", name="require_approval_bool"),
    )

    policy_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tool_name: Mapped[str]
    persona_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("personas.persona_id", ondelete="CASCADE"),
        nullable=True,
    )
    user_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=True,
    )
    require_approval: Mapped[int] = mapped_column(default=1, server_default="1")
    note: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp()
    )

    def __repr__(self) -> str:
        return (
            f"<ToolPolicy #{self.policy_id} {self.tool_name} "
            f"persona={self.persona_id!r} user={self.user_id!r} "
            f"approval={self.require_approval}>"
        )


__all__ = ["ToolPolicy"]
