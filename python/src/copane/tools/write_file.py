"""``write_file`` — write content to a file (requires user approval).

Shows a diff preview and asks the user to confirm.  Supports *y* (yes),
*n* (no), and *a* (always allow for the rest of this session).

NOTE: This tool overwrites the entire file.  For small, targeted edits
use ``edit_file`` instead — it only sends the changed snippet, not the
whole file.
"""

import os
from typing import Annotated

from agents import function_tool
from copane.tracing import traceable
from pydantic import Field

from ._base import ToolResult, _strip_config_from_schema


@function_tool(needs_approval=True)
@traceable(run_type="tool", name="Write File")
async def write_file(
    path: Annotated[str, Field(description="Absolute or relative path of the file to write")],
    content: Annotated[str, Field(description="Full text content to write to the file")],
) -> ToolResult:
    """Write content to a file. Shows a diff preview and asks the user to confirm.

    Supports *y* (yes), *n* (no), and *a* (always allow for the rest of
    this session).
    NOTE: This tool overwrites the entire file. For small, targeted edits
    use edit_file instead — it only sends the changed snippet.
    If you want to make changes to an existing file, you have to read the file thoroughly, 
    make the necessary changes to the content, and then write it back using this tool.
    """
    # Create parent directories if they don't exist
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return ToolResult(
        success=True,
        output=f"Wrote {len(content)} chars to {path}",
    )


_strip_config_from_schema(write_file.params_json_schema)


# ---------------------------------------------------------------------------
# Summarizer
# ---------------------------------------------------------------------------


def summarize(args: dict, output: str) -> str | None:
    """Produce a one-line summary of a ``write_file`` call.

    ``write_file`` results are small — just repeat the confirmation line.
    """
    path = args.get("path", "?")
    return f"- {path}: {output}"
