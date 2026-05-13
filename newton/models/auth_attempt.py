"""AuthAttempt — every voice/face/pin/passphrase attempt for security audit."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newton.models.base import Base

if TYPE_CHECKING:
    from newton.models.user import User


class AuthAttempt(Base):
    """One authentication attempt — success or failure.

    Retained after user deletion (FK uses SET NULL) so the security trail
    survives account removal.
    """

    __tablename__ = "auth_attempts"
    __table_args__ = (
        CheckConstraint(
            "method IN ('voice','face','pin','passphrase')",
            name="method_enum",
        ),
        CheckConstraint("success IN (0,1)", name="success_bool"),
    )

    attempt_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Best guess of who tried; NULL if completely unrecognized.
    attempted_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    method: Mapped[str]
    success: Mapped[int]
    # Voice / face matching score; NULL for pin/passphrase (boolean).
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp()
    )

    user: Mapped[User | None] = relationship(
        back_populates="auth_attempts",
        foreign_keys=[attempted_user_id],
    )

    def __repr__(self) -> str:
        return (
            f"<AuthAttempt #{self.attempt_id} method={self.method!r} "
            f"success={bool(self.success)} user={self.attempted_user_id!r}>"
        )


__all__ = ["AuthAttempt"]
