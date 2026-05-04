"""``grep_files`` — search for a regex pattern across files."""

import os
import shlex
import subprocess
from typing import Annotated

from agents import function_tool
from langsmith import traceable
from pydantic import Field

from ._base import (
    ToolResult,
    _MAX_GREP_OUTPUT,
    _strip_config_from_schema,
    _truncate,
)


@function_tool
@traceable(run_type="tool", name="Grep Files")
def grep_files(
    pattern: Annotated[str, Field(description="Regular expression pattern to search for")],
    path: Annotated[str, Field(
        description="Directory or file path to search in")] = ".",
    file_glob: Annotated[str, Field(
        description="Glob pattern to filter files (e.g. '*.py', '*.md')")] = "*",
) -> ToolResult:
    """Search for a regex pattern across files. Returns matches with line numbers."""
    safe_pattern = shlex.quote(pattern)
    safe_path = shlex.quote(path)
    safe_glob = shlex.quote(file_glob)

    try:
        result = subprocess.run(
            f"grep -rn --include={safe_glob} -E -e {safe_pattern} -- {safe_path}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            success=False,
            error="Grep timed out after 10 seconds.",
            error_type="timeout",
        )
    except OSError as e:
        return ToolResult(
            success=False,
            error=str(e),
            error_type="os_error",
        )

    body = result.stdout
    if not body.strip():
        return ToolResult(
            success=False,
            error="No matches found.",
            error_type="no_matches",
        )

    body, truncated = _truncate(body, _MAX_GREP_OUTPUT, label="output")
    return ToolResult(
        success=True,
        output=body,
        truncated=truncated,
    )


_strip_config_from_schema(grep_files.params_json_schema)


# ---------------------------------------------------------------------------
# Summarizer
# ---------------------------------------------------------------------------


def summarize(args: dict, output: str) -> str | None:
    """Produce a one-line summary of a ``grep_files`` call."""
    pattern = args.get("pattern", "?")
    # Collect unique file paths from grep output lines
    file_set: set[str] = set()
    for line in output.split("\n"):
        if ":" in line:
            file_path = line.split(":")[0]
            if file_path.strip():
                file_set.add(file_path.strip())
    file_list = sorted(file_set)
    files_display = ", ".join(file_list[:3])
    if len(file_list) > 3:
        files_display += f" (+{len(file_list) - 3} more)"
    match_count = output.count("\n") + (1 if output.strip() else 0)
    return f'- grep "{pattern}" → matches in {files_display} ({match_count} matches)'
