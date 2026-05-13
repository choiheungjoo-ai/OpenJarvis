"""Newton database engine and migration runner.

Newton owns a single SQLite database at ``<data_dir>/newton.db``.  Resolution
order for ``<data_dir>``:

    1. ``NEWTON_DATA_DIR`` environment variable, if set
    2. ``<project_root>/data``

The OpenJarvis databases under ``~/.openjarvis/`` are **not** touched.

Public API
----------
    get_engine()        → sqlalchemy.Engine     (cached)
    get_session()       → context manager       (SQLAlchemy Session)
    init_db()           → list[int]             (newly applied versions)
    migration_status()  → MigrationStatus       (applied + pending)

Migrations
----------
SQL files live under ``<project_root>/migrations/`` and are named
``NNN_description.sql`` (3-digit zero-padded prefix).  ``_migrations``
records which versions have been applied; reapplying a file is idempotent
because every migration ends with ``INSERT OR IGNORE INTO _migrations``.

The runner wraps each file in a single transaction so partial failures
roll back cleanly.

Foreign keys
------------
SQLite ignores foreign keys by default.  We turn them on with a
``connect`` event handler so **every** connection through the engine has
them enforced — no way to forget at a call site.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

# ─────────────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────────────


class DataError(RuntimeError):
    """Raised when the data directory or migrations cannot be used."""


# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────


def _project_root() -> Path:
    # newton/db.py  →  newton/  →  <project root>
    return Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    env = os.environ.get("NEWTON_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return _project_root() / "data"


def _migrations_dir() -> Path:
    return _project_root() / "migrations"


def _db_path() -> Path:
    return _data_dir() / "newton.db"


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────


@cache
def get_engine() -> Engine:
    """Return the (cached) SQLAlchemy Engine for Newton's SQLite database.

    The data directory is created on first call.  Foreign keys are enabled
    on every connection via a ``connect`` event listener.
    """
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    db_path = _db_path()
    url = f"sqlite:///{db_path}"

    engine = create_engine(
        url,
        # ``future=True`` is implicit in SA 2.x but keeping it explicit
        # in case OpenJarvis pins an older version.
        future=True,
        # Allow access from multiple threads (CLI is sync but FastAPI later
        # may serve from worker threads).
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    return engine


@cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def get_session() -> Iterator[Session]:
    """Context manager that yields a SQLAlchemy Session.

    Commits on clean exit, rolls back on exception, always closes.
    """
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ─────────────────────────────────────────────────────────────────────────────
# Migrations
# ─────────────────────────────────────────────────────────────────────────────


_MIGRATION_FILENAME_RE = re.compile(r"^(\d+)_[\w-]+\.sql$")


@dataclass(frozen=True)
class Migration:
    """One on-disk migration file."""

    version: int
    path: Path

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class MigrationStatus:
    """Snapshot of applied vs pending migrations."""

    applied: list[int]
    pending: list[Migration]

    @property
    def is_up_to_date(self) -> bool:
        return not self.pending


def _discover_migrations() -> list[Migration]:
    """All migration files in alphanumeric order by filename version prefix."""
    mdir = _migrations_dir()
    if not mdir.is_dir():
        raise DataError(f"migrations directory missing: {mdir}")

    found: list[Migration] = []
    for p in sorted(mdir.iterdir()):
        if not p.is_file():
            continue
        m = _MIGRATION_FILENAME_RE.match(p.name)
        if not m:
            # Skip README, .gitkeep, .swp, etc.
            continue
        found.append(Migration(version=int(m.group(1)), path=p))

    # Detect duplicate version numbers (e.g. 001_a.sql AND 001_b.sql)
    seen: set[int] = set()
    for mig in found:
        if mig.version in seen:
            dupes = [m.name for m in found if m.version == mig.version]
            raise DataError(f"duplicate migration version {mig.version}: {dupes}")
        seen.add(mig.version)

    return found


def _applied_versions(engine: Engine) -> list[int]:
    """Versions already in ``_migrations``.  Empty if the table doesn't exist yet."""
    with engine.connect() as conn:
        # Does _migrations exist?
        row = conn.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='_migrations'"
            )
        ).fetchone()
        if row is None:
            return []
        result = conn.execute(text("SELECT version FROM _migrations ORDER BY version"))
        return [r[0] for r in result.fetchall()]


def migration_status() -> MigrationStatus:
    """Return what's applied vs what's pending — does not mutate anything."""
    engine = get_engine()
    applied = _applied_versions(engine)
    on_disk = _discover_migrations()
    pending = [m for m in on_disk if m.version not in applied]
    return MigrationStatus(applied=applied, pending=pending)


def init_db() -> list[int]:
    """Apply every pending migration, in order.

    Each migration runs in its own transaction.  Returns the list of
    versions actually applied this call (empty if already up to date).
    """
    engine = get_engine()
    status = migration_status()

    applied_now: list[int] = []
    for mig in status.pending:
        sql = mig.path.read_text(encoding="utf-8")
        with engine.begin() as conn:
            # ``exec_driver_sql`` runs raw SQL through the DBAPI, which
            # honours sqlite3's ability to execute multi-statement scripts
            # when given as a single string via executescript.  SQLAlchemy
            # 2.x doesn't expose executescript directly, so we drop to the
            # driver-level connection.
            raw = conn.connection.driver_connection  # underlying sqlite3.Connection
            raw.executescript(sql)
        applied_now.append(mig.version)

    return applied_now


__all__ = [
    "DataError",
    "Migration",
    "MigrationStatus",
    "get_engine",
    "get_session",
    "init_db",
    "migration_status",
]
