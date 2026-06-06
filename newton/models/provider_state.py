"""ProviderState — the permanently-selected provider for a capability.

Schema mirrors ``migrations/004_provider_state.sql``. Only ``permanent``
swaps are persisted here; ``once`` and ``session`` scopes live in memory.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column

from newton.models.base import Base


class ProviderState(Base):
    """One row per capability: its permanent active provider."""

    __tablename__ = "provider_state"

    capability: Mapped[str] = mapped_column(primary_key=True)
    active_provider: Mapped[str]
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp()
    )

    def __repr__(self) -> str:
        return (
            f"<ProviderState {self.capability}={self.active_provider} "
            f"@{self.updated_at}>"
        )


__all__ = ["ProviderState"]
