"""UserPattern — learned behaviour signatures (time / sequence / context)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newton.models.base import Base

if TYPE_CHECKING:
    from newton.models.user import User


class UserPattern(Base):
    """A behaviour pattern Newton has learned about one user."""

    __tablename__ = "user_patterns"
    __table_args__ = (
        CheckConstraint(
            "pattern_type IN ('time','sequence','context')",
            name="pattern_type_enum",
        ),
    )

    pattern_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"),
    )
    pattern_type: Mapped[str]
    pattern_data_json: Mapped[str | None] = mapped_column(nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    occurrences: Mapped[int] = mapped_column(default=1, server_default="1")
    last_seen: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp()
    )

    user: Mapped[User] = relationship(back_populates="patterns")

    def __repr__(self) -> str:
        return (
            f"<UserPattern #{self.pattern_id} user={self.user_id!r} "
            f"type={self.pattern_type!r} occurrences={self.occurrences}>"
        )


__all__ = ["UserPattern"]
