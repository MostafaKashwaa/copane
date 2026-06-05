"""``edit_file`` — replace a string in a file with surgical precision.

Finds ``old_string`` in the file at *path* and replaces it with
``new_string``.  Unlike ``write_file``, this only sends the changed
snippet, not the whole file — ideal for small, targeted edits.

All edits require user approval; a diff is shown before the change
is applied.
"""

import difflib
import os
from typing import Annotated

from agents import function_tool
from copane.tracing import traceable
from pydantic import Field

from ._base import ToolResult, _strip_config_from_schema

_DIFF_LINE_LIMIT = 30  # max lines of unified diff to include in tool output


@function_tool(needs_approval=True)
@traceable(run_type="tool", name="Edit File")
async def edit_file(
    path: Annotated[str, Field(description="Absolute or relative path of the file to edit")],
    old_string: Annotated[str, Field(
        description="Exact text to find and replace in the file. Must match exactly and be unique."
    )],
    new_string: Annotated[str, Field(description="Replacement text")],
) -> ToolResult:
    """Replace a string in a file with surgical precision (requires user approval).

    The tool finds ``old_string`` in the file and replaces it with
    ``new_string``.  If ``old_string`` is not found or matches multiple
    locations the tool returns an error — make the match string
    specific enough to be unique (include a few lines of surrounding
    context).

    For new files or large rewrites, use ``write_file`` instead.
    """
    if not os.path.exists(path):
        return ToolResult(
            success=False,
            error=f"File not found: {path}",
            error_type="file_not_found",
        )

    if not old_string:
        return ToolResult(
            success=False,
            error="old_string must be non-empty. For new files or large rewrites, use write_file.",
            error_type="invalid_argument",
        )

    try:
        with open(path) as f:
            original = f.read()
    except OSError as e:
        return ToolResult(
            success=False,
            error=str(e),
            error_type="read_error",
        )

    count = original.count(old_string)
    if count == 0:
        return ToolResult(
            success=False,
            error=(
                f"old_string not found in {path}. "
                "The file may have been modified since you last read it."
            ),
            error_type="not_found",
        )
    if count > 1:
        return ToolResult(
            success=False,
            error=(
                f"old_string matches {count} locations in {path}. "
                "Make it more specific by including more surrounding context."
            ),
            error_type="ambiguous_match",
        )

    new_content = original.replace(old_string, new_string, 1)

    try:
        with open(path, "w") as f:
            f.write(new_content)
    except OSError as e:
        return ToolResult(
            success=False,
            error=str(e),
            error_type="write_error",
        )

    before = original[: original.index(old_string)]
    line = before.count("\n") + 1

    # Build a truncated unified diff so the model can see exactly what changed.
    diff_lines = list(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
    diff_text = "".join(diff_lines[:_DIFF_LINE_LIMIT])
    if len(diff_lines) > _DIFF_LINE_LIMIT:
        diff_text += f"\n... ({len(diff_lines) - _DIFF_LINE_LIMIT} more diff lines omitted)\n"
    elif not diff_text:
        diff_text = "(no changes)"

    return ToolResult(
        success=True,
        output=(
            f"Edited {path}: replaced {len(old_string)} chars "
            f"with {len(new_string)} chars at line {line}.\n\n"
            f"{diff_text}"
        ),
    )


_strip_config_from_schema(edit_file.params_json_schema)


# ---------------------------------------------------------------------------
# Summarizer
# ---------------------------------------------------------------------------


def summarize(args: dict, output: str) -> str | None:
    """Produce a one-line summary of an ``edit_file`` call."""
    path = args.get("path", "?")
    return f"- {path}: {output}"
