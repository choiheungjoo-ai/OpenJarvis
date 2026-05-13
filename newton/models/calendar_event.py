"""CalendarEvent — mirrored from Google / Outlook / CalDAV."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newton.models.base import Base

if TYPE_CHECKING:
    from newton.models.user import User


class CalendarEvent(Base):
    """One calendar event scoped to a single user.

    ``external_id`` lets us idempotently re-sync from the source provider.
    """

    __tablename__ = "calendar_events"
    __table_args__ = (
        CheckConstraint(
            "source IN ('google','outlook','caldav')",
            name="source_enum",
        ),
    )

    event_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str]
    external_id: Mapped[str | None] = mapped_column(nullable=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"),
    )
    title: Mapped[str | None] = mapped_column(nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(nullable=True)
    location: Mapped[str | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(nullable=True)
    last_synced: Mapped[datetime | None] = mapped_column(nullable=True)

    user: Mapped[User] = relationship(back_populates="calendar_events")

    def __repr__(self) -> str:
        return (
            f"<CalendarEvent #{self.event_id} {self.source}:{self.external_id!r} "
            f"user={self.user_id!r} title={self.title!r}>"
        )


__all__ = ["CalendarEvent"]
