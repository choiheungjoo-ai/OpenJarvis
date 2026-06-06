"""Shared path resolution for builtin tools.

Mirrors the resolution in ``newton/db.py`` so tools and the DB agree on
where Newton's data lives:

    1. ``NEWTON_DATA_DIR`` environment variable, if set
    2. ``<project_root>/data``

``ToolContext.extra["data_dir"]`` overrides both when present, so callers
(and tests) can pin a sandbox without touching the environment.
"""

from __future__ import annotations

import os
from pathlib import Path

from newton.tools.base import ToolContext

# newton/tools/builtin/_paths.py -> newton/tools/builtin -> newton/tools
#   -> newton -> <project root>
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def data_dir(context: ToolContext | None = None) -> Path:
    """Resolve Newton's data directory.

    Order: context override -> NEWTON_DATA_DIR -> <project_root>/data.
    """
    if context is not None:
        override = context.extra.get("data_dir")
        if override:
            return Path(override).expanduser().resolve()
    env = os.environ.get("NEWTON_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return _PROJECT_ROOT / "data"


def scratch_dir(context: ToolContext | None = None) -> Path:
    """The only tree builtin write-tools may touch: ``<data_dir>/tool_scratch``."""
    return data_dir(context) / "tool_scratch"
