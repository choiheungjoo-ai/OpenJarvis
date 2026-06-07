"""ToolPolicy — per (tool, persona, user) approval decision.

Schema mirrors ``migrations/005_tool_policy_decision.sql``. A NULL
``persona_id`` or ``user_id`` is a wildcard ("any"). ``decision`` is one of
``auto_allow`` / ``require_approval`` / ``always_deny``. Resolution and the
risk-based default live in ``newton/tools/policy.py``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from newton.models.base import Base

DECISION_AUTO_ALLOW = "auto_allow"
DECISION_REQUIRE_APPROVAL = "require_approval"
DECISION_ALWAYS_DENY = "always_deny"
DECISIONS = (DECISION_AUTO_ALLOW, DECISION_REQUIRE_APPROVAL, DECISION_ALWAYS_DENY)


class ToolPolicy(Base):
    """One policy row. Most specific matching row wins at lookup."""

    __tablename__ = "tool_policies"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('auto_allow','require_approval','always_deny')",
            name="decision_enum",
        ),
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
    decision: Mapped[str] = mapped_column(
        default=DECISION_REQUIRE_APPROVAL,
        server_default=DECISION_REQUIRE_APPROVAL,
    )
    note: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp()
    )

    def __repr__(self) -> str:
        return (
            f"<ToolPolicy #{self.policy_id} {self.tool_name} "
            f"persona={self.persona_id!r} user={self.user_id!r} "
            f"decision={self.decision!r}>"
        )


__all__ = [
    "DECISIONS",
    "DECISION_ALWAYS_DENY",
    "DECISION_AUTO_ALLOW",
    "DECISION_REQUIRE_APPROVAL",
    "ToolPolicy",
]
