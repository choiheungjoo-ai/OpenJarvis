"""ProactiveNotification — Newton-initiated nudges and the user's response."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newton.models.base import Base

if TYPE_CHECKING:
    from newton.models.user import User


class ProactiveNotification(Base):
    """One nudge sent unprompted (JARVIS-style).

    The trigger pattern survives the user even if pattern is later deleted,
    so ``trigger_pattern_id`` uses SET NULL.  The user reference however
    cascades — there is no point keeping a nudge tied to a deleted user.
    """

    __tablename__ = "proactive_notifications"
    __table_args__ = (
        CheckConstraint(
            "user_response IN ('accepted','rejected','ignored')",
            name="user_response_enum",
        ),
    )

    notification_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"),
    )
    trigger_pattern_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_patterns.pattern_id", ondelete="SET NULL"),
        nullable=True,
    )
    notification_text: Mapped[str]
    sent_at: Mapped[datetime] = mapped_column(server_default=func.current_timestamp())
    user_response: Mapped[str | None] = mapped_column(nullable=True)
    response_at: Mapped[datetime | None] = mapped_column(nullable=True)

    user: Mapped[User] = relationship(back_populates="notifications")

    def __repr__(self) -> str:
        return (
            f"<ProactiveNotification #{self.notification_id} "
            f"user={self.user_id!r} response={self.user_response!r}>"
        )


__all__ = ["ProactiveNotification"]
