"""ScreenCapture — periodic screenshot for context awareness.

The block-8 sweeper polls ``purge_after`` to auto-delete sensitive frames.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newton.models.base import Base

if TYPE_CHECKING:
    from newton.models.user import User


class ScreenCapture(Base):
    """A captured screen frame and its analysis."""

    __tablename__ = "screen_captures"
    __table_args__ = (
        CheckConstraint("is_sensitive IN (0,1)", name="is_sensitive_bool"),
    )

    capture_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"),
    )
    captured_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp()
    )
    analysis_summary: Mapped[str | None] = mapped_column(nullable=True)
    is_sensitive: Mapped[int] = mapped_column(default=0, server_default="0")
    purge_after: Mapped[datetime | None] = mapped_column(nullable=True)

    user: Mapped[User] = relationship(back_populates="screen_captures")

    def __repr__(self) -> str:
        flag = " SENSITIVE" if self.is_sensitive else ""
        return (
            f"<ScreenCapture #{self.capture_id} user={self.user_id!r}"
            f" @{self.captured_at}{flag}>"
        )


__all__ = ["ScreenCapture"]
