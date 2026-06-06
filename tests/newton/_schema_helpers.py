"""Schema-introspection helpers for tests.

These derive expectations from ground truth (the migrations directory, the
models package on disk) instead of hardcoding them, so adding a migration or
a model does not require editing assertion literals across the suite.

Two sources of truth:
  * ``expected_migration_versions()`` reads ``migrations/NNN_*.sql``.
  * ``model_classes_on_disk()`` imports each ``newton/models/*.py`` module
    and collects Base subclasses actually defined there.

The model helper deliberately scans the filesystem rather than reading
``newton.models.__all__`` — that way a model added as a file but forgotten
in ``__all__`` is still caught (the original point of the export smoke test).
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import newton.db as _db
import newton.models as _models_pkg
from newton.models.base import Base


def expected_migration_versions() -> list[int]:
    """All migration versions present on disk, ascending.

    Reuses the runner's own discovery so the test agrees with production
    resolution exactly.
    """
    return sorted(m.version for m in _db._discover_migrations())


def model_classes_on_disk() -> dict[str, type]:
    """Map class name -> class for every Base subclass defined under
    ``newton/models/`` (excluding Base itself).

    Imports each submodule so the class objects exist, then filters to
    classes whose ``__module__`` is inside the models package (so re-exports
    and imported helpers from elsewhere are not miscounted).
    """
    pkg_path = Path(_models_pkg.__file__).parent
    pkg_name = _models_pkg.__name__

    for info in pkgutil.iter_modules([str(pkg_path)]):
        if info.name.startswith("_"):
            continue  # skip private/sandbox modules like _stubs
        importlib.import_module(f"{pkg_name}.{info.name}")

    found: dict[str, type] = {}
    for cls in Base.__subclasses__():
        if cls is Base:
            continue
        mod = cls.__module__
        if not mod.startswith(pkg_name + "."):
            continue
        # Mirror the import-skip rule: a class defined in a private module
        # (leading underscore in its final path segment) is not a shipped
        # model. Keeps the "defined on disk" set consistent with what we
        # actually scan.
        last_segment = mod.rsplit(".", 1)[-1]
        if last_segment.startswith("_"):
            continue
        found[cls.__name__] = cls
    return found


def expected_model_names() -> set[str]:
    """Model class names that should appear in ``newton.models.__all__``."""
    return set(model_classes_on_disk())
