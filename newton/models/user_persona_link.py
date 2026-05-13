"""UserPersonaLink — which users can use which personas (with per-user default)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newton.models.base import Base

if TYPE_CHECKING:
    from newton.models.persona import Persona
    from newton.models.user import User


class UserPersonaLink(Base):
    """Many-to-many join between users and personas, plus a default flag."""

    __tablename__ = "user_persona_link"
    __table_args__ = (CheckConstraint("is_default IN (0,1)", name="is_default_bool"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    persona_id: Mapped[str] = mapped_column(
        ForeignKey("personas.persona_id", ondelete="CASCADE"),
        primary_key=True,
    )
    is_default: Mapped[int] = mapped_column(default=0, server_default="0")

    user: Mapped[User] = relationship(back_populates="persona_links")
    persona: Mapped[Persona] = relationship(back_populates="user_links")

    def __repr__(self) -> str:
        return f"<UserPersonaLink user={self.user_id!r} persona={self.persona_id!r}>"


__all__ = ["UserPersonaLink"]
