"""Persona — Butler / JARVIS / Friday and any later additions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newton.models.base import Base

if TYPE_CHECKING:
    from newton.models.chat_session import ChatSession
    from newton.models.user import User
    from newton.models.user_persona_link import UserPersonaLink


class Persona(Base):
    """A persona is the personality + voice + permissions layer."""

    __tablename__ = "personas"
    __table_args__ = (
        CheckConstraint("is_public IN (0,1)", name="is_public_bool"),
        CheckConstraint("is_default IN (0,1)", name="is_default_bool"),
    )

    persona_id: Mapped[str] = mapped_column(primary_key=True)
    display_name: Mapped[str]
    is_public: Mapped[int] = mapped_column(default=0, server_default="0")
    is_default: Mapped[int] = mapped_column(default=0, server_default="0")
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    # May contain ``${OWNER_DISPLAY_NAME}`` — substitution happens at LLM call time.
    system_prompt: Mapped[str | None] = mapped_column(nullable=True)
    # JSON-encoded: either VoiceConfig dict, or {ko: VoiceConfig, en: VoiceConfig}.
    # Stored as TEXT in SQLite; the application layer parses.
    voice_config_json: Mapped[str | None] = mapped_column(nullable=True)
    color: Mapped[str | None] = mapped_column(nullable=True)
    lora_adapter_path: Mapped[str | None] = mapped_column(nullable=True)  # block 9
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp()
    )

    # ── Relationships ──
    owner: Mapped[User | None] = relationship(
        back_populates="owned_personas",
        foreign_keys=[owner_user_id],
    )
    user_links: Mapped[list[UserPersonaLink]] = relationship(
        back_populates="persona",
        cascade="all, delete-orphan",
    )
    # ChatSessions: FK uses ON DELETE RESTRICT — deleting a persona with
    # active sessions is blocked at the DB level.  No cascade here.
    chat_sessions: Mapped[list[ChatSession]] = relationship(back_populates="persona")

    def __repr__(self) -> str:
        return (
            f"<Persona {self.persona_id!r} display={self.display_name!r} "
            f"owner={self.owner_user_id!r}>"
        )


__all__ = ["Persona"]
