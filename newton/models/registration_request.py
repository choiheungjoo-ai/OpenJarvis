"""RegistrationRequest — a new-user proposal awaiting sir's approval."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from newton.models.base import Base


class RegistrationRequest(Base):
    """Pending registration of a new household member."""

    __tablename__ = "registration_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name="status_enum",
        ),
    )

    request_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    requested_name: Mapped[str]
    requested_persona: Mapped[str | None] = mapped_column(nullable=True)
    voice_sample_path: Mapped[str | None] = mapped_column(nullable=True)
    face_sample_path: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(default="pending", server_default="pending")
    requested_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp()
    )
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    decided_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<RegistrationRequest #{self.request_id} "
            f"name={self.requested_name!r} status={self.status!r}>"
        )


__all__ = ["RegistrationRequest"]
