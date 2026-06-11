"""User — a registered human (sir/Alex, gf/Stella, plus any later adds)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, LargeBinary, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newton.models.base import Base

if TYPE_CHECKING:
    from newton.models.auth_attempt import AuthAttempt
    from newton.models.calendar_event import CalendarEvent
    from newton.models.chat_session import ChatSession
    from newton.models.persona import Persona
    from newton.models.proactive_notification import ProactiveNotification
    from newton.models.screen_capture import ScreenCapture
    from newton.models.user_pattern import UserPattern
    from newton.models.user_persona_link import UserPersonaLink


class User(Base):
    """Registered user.  ``user_id`` is a stable opaque slug like 'sir' / 'gf'."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "retry_profile IN ('strict','normal','relaxed')",
            name="retry_profile_enum",
        ),
    )

    user_id: Mapped[str] = mapped_column(primary_key=True)
    display_name: Mapped[str]
    voice_embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    face_embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # ``default_persona_id`` is a soft pointer — no FK in 1.4 SQL.  Resolved
    # at lookup time, allowing a user to reference a persona that may have
    # been later renamed without an immediate cascade.
    default_persona_id: Mapped[str | None] = mapped_column(nullable=True)

    # STT contextual-biasing dictionary (block 3.9): JSON array of
    # entity strings harvested from this user's vault notes.
    stt_bias_dict_json: Mapped[str] = mapped_column(default="[]", server_default="[]")
    pin_hash: Mapped[str | None] = mapped_column(nullable=True)
    passphrase_hash: Mapped[str | None] = mapped_column(nullable=True)
    retry_profile: Mapped[str] = mapped_column(
        default="normal", server_default="normal"
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp()
    )

    # ── Relationships (only the ones with obvious traversal patterns) ──
    owned_personas: Mapped[list[Persona]] = relationship(
        back_populates="owner",
        foreign_keys="Persona.owner_user_id",
    )
    persona_links: Mapped[list[UserPersonaLink]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    chat_sessions: Mapped[list[ChatSession]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    patterns: Mapped[list[UserPattern]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    notifications: Mapped[list[ProactiveNotification]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    screen_captures: Mapped[list[ScreenCapture]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    calendar_events: Mapped[list[CalendarEvent]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    # auth_attempts intentionally has no back_populates here: the FK uses
    # ON DELETE SET NULL, so attempts survive the user.
    auth_attempts: Mapped[list[AuthAttempt]] = relationship(
        back_populates="user",
        foreign_keys="AuthAttempt.attempted_user_id",
    )

    def __repr__(self) -> str:
        return f"<User {self.user_id!r} display={self.display_name!r}>"


__all__ = ["User"]
