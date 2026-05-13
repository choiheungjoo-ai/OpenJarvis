"""SQLAlchemy declarative base shared by every Newton model.

Why a custom base?
    * Single place to attach engine-wide concerns (naming, MetaData).
    * The constraint-naming convention below lets Alembic (if we ever pull
      it in) and our own migration files generate stable identifier names.

Conventions
-----------
``__tablename__`` exactly matches ``migrations/001_initial.sql``.
``Mapped[T]`` + ``mapped_column`` (SQLAlchemy 2.x style) — no legacy
``Column(...)`` declarations.

Timestamps
----------
We let SQLite stamp ``created_at`` itself via ``server_default``.  This
avoids Python clock drift and keeps inserts atomic in SQL.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Stable, predictable constraint names.  Useful for future Alembic autogen
# and for reading EXPLAIN output.
_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Root for every Newton ORM model."""

    metadata = MetaData(naming_convention=_NAMING_CONVENTION)


__all__ = ["Base"]
