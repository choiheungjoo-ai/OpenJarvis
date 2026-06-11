"""Newton builtin tools (Block 2).

These are the first real tools, one per risk band exercised in Block 2:
    echo          — risk 0 (SAFE)
    system_info   — risk 1 (READ_LOCAL)
    echo_to_file  — risk 2 (WRITE_LOCAL)
"""

from __future__ import annotations

from newton.tools.builtin.echo import EchoTool
from newton.tools.builtin.echo_to_file import EchoToFileTool
from newton.tools.builtin.system_info import SystemInfoTool
from newton.tools.builtin.vault_search import VaultSearchTool
from newton.tools.builtin.vault_write import VaultWriteTool
from newton.tools.registry import ToolRegistry

__all__ = [
    "EchoTool",
    "EchoToFileTool",
    "SystemInfoTool",
    "VaultSearchTool",
    "VaultWriteTool",
    "register_builtins",
]


def register_builtins(registry: ToolRegistry) -> None:
    """Register all builtin tools into a registry."""
    registry.register(EchoTool())
    registry.register(SystemInfoTool())
    registry.register(EchoToFileTool())
    registry.register(VaultSearchTool())
    registry.register(VaultWriteTool())
