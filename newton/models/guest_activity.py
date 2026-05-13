"""GuestActivity — quarantined records of what an unregistered visitor did."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newton.models.base import Base

if TYPE_CHECKING:
    from newton.models.chat_session import ChatSession


class GuestActivity(Base):
    """A guest's action queued for sir's review and possible promotion."""

    __tablename__ = "guest_activity"
    __table_args__ = (
        CheckConstraint(
            "activity_type IN ('search','code','chat','learning')",
            name="activity_type_enum",
        ),
        CheckConstraint(
            "status IN ('pending_review','accepted','rejected','promoted')",
            name="status_enum",
        ),
    )

    activity_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.session_id", ondelete="SET NULL"),
        nullable=True,
    )
    activity_type: Mapped[str | None] = mapped_column(nullable=True)
    # Short brief for sir's review feed.
    summary: Mapped[str | None] = mapped_column(nullable=True)
    # Path to the full content under ``_guest_quarantine/`` on disk.
    raw_content_path: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(
        default="pending_review",
        server_default="pending_review",
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    session: Mapped[ChatSession | None] = relationship(
        back_populates="guest_activities"
    )

    def __repr__(self) -> str:
        return (
            f"<GuestActivity #{self.activity_id} type={self.activity_type!r} "
            f"status={self.status!r}>"
        )


__all__ = ["GuestActivity"]
