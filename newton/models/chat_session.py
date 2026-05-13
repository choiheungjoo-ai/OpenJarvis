"""ChatSession — one continuous conversation with a single persona.

Note on the name: the SQL table is ``sessions`` (we keep the SQL noun) but
the Python class is ``ChatSession`` to avoid shadowing ``sqlalchemy.orm.Session``.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newton.models.base import Base

if TYPE_CHECKING:
    from newton.models.guest_activity import GuestActivity
    from newton.models.message import Message
    from newton.models.persona import Persona
    from newton.models.user import User


class ChatSession(Base):
    """A user-to-persona dialogue, possibly long-lived."""

    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"),
    )
    persona_id: Mapped[str] = mapped_column(
        ForeignKey("personas.persona_id", ondelete="RESTRICT"),
    )
    started_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp()
    )
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Channel, device, locale — free-form JSON encoded as TEXT.
    metadata_json: Mapped[str | None] = mapped_column(nullable=True)

    # ── Relationships ──
    user: Mapped[User] = relationship(back_populates="chat_sessions")
    persona: Mapped[Persona] = relationship(back_populates="chat_sessions")
    messages: Mapped[list[Message]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
    # Guest activity holds the session by SET NULL so we don't cascade.
    guest_activities: Mapped[list[GuestActivity]] = relationship(
        back_populates="session"
    )

    def __repr__(self) -> str:
        return (
            f"<ChatSession {self.session_id!r} user={self.user_id!r} "
            f"persona={self.persona_id!r}>"
        )


__all__ = ["ChatSession"]
