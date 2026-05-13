"""SystemMetric — CPU / GPU / memory / battery / temp / network sample.

No FK: global system state, not per-user.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from newton.models.base import Base


class SystemMetric(Base):
    """A single sampled metric value."""

    __tablename__ = "system_metrics"
    __table_args__ = (
        CheckConstraint(
            "metric_type IN ('cpu','gpu','memory','battery','temperature','network')",
            name="metric_type_enum",
        ),
    )

    metric_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    metric_type: Mapped[str]
    value: Mapped[float]
    captured_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp()
    )

    def __repr__(self) -> str:
        return (
            f"<SystemMetric #{self.metric_id} {self.metric_type}={self.value} "
            f"@{self.captured_at}>"
        )


__all__ = ["SystemMetric"]
