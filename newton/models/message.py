"""Message — one turn in a ChatSession."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newton.models.base import Base

if TYPE_CHECKING:
    from newton.models.chat_session import ChatSession


class Message(Base):
    """A single turn — user / assistant / system / tool — in a chat session."""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user','assistant','system','tool')",
            name="role_enum",
        ),
    )

    message_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
    )
    role: Mapped[str]
    content: Mapped[str | None] = mapped_column(nullable=True)
    tool_calls_json: Mapped[str | None] = mapped_column(nullable=True)
    # Filled in block 5 by the vision pipeline.  Free text for now.
    emotion_snapshot: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp()
    )

    session: Mapped[ChatSession] = relationship(back_populates="messages")

    def __repr__(self) -> str:
        snippet = (self.content or "")[:30]
        return f"<Message #{self.message_id} role={self.role!r} {snippet!r}>"


__all__ = ["Message"]
