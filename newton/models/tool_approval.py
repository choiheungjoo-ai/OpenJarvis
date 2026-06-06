"""ToolApproval — audit record of an approval-gated tool decision.

Schema mirrors ``migrations/003_tool_approvals.sql``.  Only decisions that
involved approval are recorded; auto-allowed calls are not.  ``user_id`` is
SET NULL on user deletion so the trail outlives the user.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from newton.models.base import Base


class ToolApproval(Base):
    """One approval decision: approved / denied / timeout."""

    __tablename__ = "tool_approvals"
    __table_args__ = (
        CheckConstraint("risk_level BETWEEN 0 AND 4", name="risk_level_range"),
        CheckConstraint(
            "decision IN ('approved','denied','timeout')", name="decision_enum"
        ),
        CheckConstraint(
            "policy_source IN ('db','risk_default')", name="policy_source_enum"
        ),
    )

    approval_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tool_name: Mapped[str]
    risk_level: Mapped[int]
    persona_id: Mapped[str | None] = mapped_column(nullable=True)
    user_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    decision: Mapped[str]
    policy_source: Mapped[str | None] = mapped_column(nullable=True)
    channel: Mapped[str | None] = mapped_column(nullable=True)
    args_summary: Mapped[str | None] = mapped_column(nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp()
    )

    def __repr__(self) -> str:
        return (
            f"<ToolApproval #{self.approval_id} {self.tool_name} "
            f"{self.decision} user={self.user_id!r} @{self.decided_at}>"
        )


__all__ = ["ToolApproval"]
