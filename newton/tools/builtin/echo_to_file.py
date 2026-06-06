"""echo_to_file — write text to a file. Risk 2 (WRITE_LOCAL).

Writes are confined to ``<data_dir>/tool_scratch/``. Any path that escapes
that tree (via ``..``, absolute paths, or symlinks) is refused before any
I/O happens. This is the tool the Step 2.6 approval hook gates on.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from newton.tools.base import RiskLevel, Tool, ToolContext, ToolResult
from newton.tools.builtin._paths import scratch_dir


class EchoToFileArgs(BaseModel):
    relative_path: str = Field(
        ...,
        description=(
            "Path relative to the tool scratch directory, e.g. 'note.txt' "
            "or 'sub/dir/note.txt'. Must stay inside the scratch tree."
        ),
    )
    text: str = Field(..., description="Text content to write.")
    append: bool = Field(default=False, description="Append instead of overwrite.")


class EchoToFileReturns(BaseModel):
    path: str
    bytes_written: int
    appended: bool


def _resolve_within_scratch(root, relative_path: str):
    """Return the resolved target path, or raise ValueError if it escapes root.

    ``root`` is resolved first so symlinked data dirs compare correctly.
    """
    root_resolved = root.resolve()
    candidate = (root_resolved / relative_path).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError(
            f"path escapes scratch directory: {relative_path!r} -> {candidate}"
        )
    return candidate


class EchoToFileTool(Tool):
    name = "echo_to_file"
    description = (
        "Write text to a file inside Newton's tool scratch directory. "
        "Cannot write outside that tree."
    )
    risk = RiskLevel.WRITE_LOCAL
    args_schema = EchoToFileArgs
    returns_schema = EchoToFileReturns

    async def execute(self, args: EchoToFileArgs, context: ToolContext) -> ToolResult:
        root = scratch_dir(context)
        try:
            target = _resolve_within_scratch(root, args.relative_path)
        except ValueError as exc:
            return ToolResult(status="denied", error=str(exc))

        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if args.append else "w"
        data = args.text.encode("utf-8")
        with target.open(mode, encoding="utf-8") as f:
            f.write(args.text)

        return ToolResult(
            status="ok",
            data={
                "path": str(target),
                "bytes_written": len(data),
                "appended": args.append,
            },
        )
