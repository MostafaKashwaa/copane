"""``list_files`` — list directory structure up to a certain depth."""

import os
import shlex
import subprocess
from typing import Annotated

from agents import function_tool
from langsmith import traceable
from pydantic import Field

from ._base import ToolResult, _strip_config_from_schema


@function_tool
@traceable(run_type="tool", name="List Files")
def list_files(
    path: Annotated[str, Field(description="Directory path to list")] = ".",
    depth: Annotated[int, Field(
        description="Maximum depth of directory traversal")] = 2,
) -> ToolResult:
    """List directory structure up to a certain depth."""
    # Validate the path exists early — find(1) exits 0 even for nonexistent paths
    if not os.path.exists(path):
        return ToolResult(
            success=False,
            error=f"Path not found: {path}",
            error_type="file_not_found",
        )

    safe_path = shlex.quote(path)
    try:
        result = subprocess.run(
            f"find {safe_path} -maxdepth {depth} "
            "-not -path '*/node_modules/*' "
            "-not -path '*/.git/*' "
            "-not -path '*/vendor/*' | head -200",
            shell=True,
            capture_output=True,
            text=True,
        )
    except OSError as e:
        return ToolResult(
            success=False,
            error=str(e),
            error_type="os_error",
        )

    return ToolResult(
        success=True,
        output=result.stdout or "(empty directory)",
    )


_strip_config_from_schema(list_files.params_json_schema)


# ---------------------------------------------------------------------------
# Summarizer
# ---------------------------------------------------------------------------


def summarize(args: dict, output: str) -> str | None:
    """Produce a one-line summary of a ``list_files`` call."""
    path = args.get("path", ".")
    depth = args.get("depth", 2)
    file_count = output.count("\n") + (1 if output.strip() else 0)
    return f"- {path} (depth {depth}): {file_count} entries"
