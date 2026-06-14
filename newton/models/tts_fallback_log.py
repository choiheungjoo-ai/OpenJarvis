"""TTSFallbackLog — one row per TTS fallback event (block 5 step 5.13)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from newton.models.base import Base


class TTSFallbackLog(Base):
    """A single (primary engine → fallback engine) transition for TTS."""

    __tablename__ = "tts_fallback_log"

    log_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str]
    persona_id: Mapped[str] = mapped_column(
        ForeignKey("personas.persona_id", ondelete="RESTRICT"),
    )
    language: Mapped[str]
    primary_engine: Mapped[str]
    fallback_engine: Mapped[str]
    failure_reason: Mapped[str]
    text_length: Mapped[int | None] = mapped_column(nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp()
    )


__all__ = ["TTSFallbackLog"]
