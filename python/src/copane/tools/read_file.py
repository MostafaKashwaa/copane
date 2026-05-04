"""``read_file`` — read a file or line range from disk.

Full file contents are returned within the current turn.  Between
turns, file-read results are summarized to metadata (path, line count,
purpose hint) — re-read files at the start of a new turn if exact
content is needed.
"""

import os
import re
from typing import Annotated

from agents import function_tool
from langsmith import traceable
from pydantic import Field

from ._base import (
    ToolResult,
    _MAX_READ_FILE_SAFETY_LIMIT,
    _strip_config_from_schema,
    _truncate,
)

# ---------------------------------------------------------------------------
# Purpose extraction (deterministic)
# ---------------------------------------------------------------------------

_MAX_PURPOSE_CHARS = 120


def _extract_purpose(file_content: str, file_path: str = "") -> str:
    """Extract a one-line purpose description from file contents.

    Tries, in order:
    1. Module docstring (first ``\"\"\"...\"\"\"`` or ``'''...'''`` block)
    2. First ``class`` or ``def`` definition
    3. First non-blank, non-comment line
    4. Extension-based fallback label

    Result is capped at ``_MAX_PURPOSE_CHARS`` characters.
    """
    if not file_content.strip():
        return "(empty file)"

    # 1. Try docstring
    m = re.match(
        r'^\s*(?:"{3}(.+?)"{3}|\'{3}(.+?)\'{3})',
        file_content,
        re.DOTALL,
    )
    if m:
        docstring = (m.group(1) or m.group(2)).strip()
        # Take first sentence / first line
        doc_first_line = docstring.split("\n")[0].strip()
        if doc_first_line:
            return doc_first_line[:_MAX_PURPOSE_CHARS]

    # 2. Try first class or def
    m = re.search(
        r"^\s*(class\s+\w+|def\s+\w+)",
        file_content,
        re.MULTILINE,
    )
    if m:
        return m.group(1).strip()[:_MAX_PURPOSE_CHARS]

    # 3. First non-blank, non-comment line
    for line in file_content.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith(("#", "//", "/*", "*", "*/")):
            return stripped[:_MAX_PURPOSE_CHARS]

    # 4. Extension-based fallback
    ext = os.path.splitext(file_path)[1].lower() if file_path else ""
    labels = {
        ".py": "(Python source)",
        ".js": "(JavaScript source)",
        ".ts": "(TypeScript source)",
        ".tsx": "(TypeScript React)",
        ".jsx": "(JavaScript React)",
        ".css": "(CSS stylesheet)",
        ".html": "(HTML document)",
        ".md": "(Markdown document)",
        ".json": "(JSON data)",
        ".yaml": "(YAML config)",
        ".yml": "(YAML config)",
        ".toml": "(TOML config)",
        ".cfg": "(config file)",
        ".ini": "(INI config)",
        ".sh": "(shell script)",
        ".bash": "(Bash script)",
        ".zsh": "(Zsh script)",
        ".vim": "(Vim script)",
        ".lua": "(Lua source)",
        ".rs": "(Rust source)",
        ".go": "(Go source)",
        ".c": "(C source)",
        ".h": "(C header)",
        ".cpp": "(C++ source)",
        ".hpp": "(C++ header)",
        ".java": "(Java source)",
        ".rb": "(Ruby source)",
        ".php": "(PHP source)",
        ".sql": "(SQL script)",
        ".dockerfile": "(Dockerfile)",
        ".makefile": "(Makefile)",
    }
    return labels.get(ext, f"({ext[1:] or 'unknown'} file)")


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


@function_tool
@traceable(run_type="tool", name="Read File")
def read_file(
    path: Annotated[str, Field(description="Absolute or relative path to the file to read")],
    start_line: Annotated[int, Field(
        description="First line number to read (1-indexed)")] = 1,
    end_line: Annotated[int, Field(
        description="Last line number to read (0 means read to end of file)")] = 0,
) -> ToolResult:
    """Read a file or a line range from it.

    Full file contents are returned within the current turn.  Between
    turns, file-read results are summarized to metadata (path, line
    count, purpose hint) — re-read files at the start of a new turn if
    exact content is needed.

    Use start_line/end_line to read a specific range rather than the
    whole file when you only need a section.
    """
    if not os.path.exists(path):
        return ToolResult(
            success=False,
            error=f"File not found: {path}",
            error_type="file_not_found",
        )

    try:
        with open(path) as f:
            lines = f.readlines()
    except OSError as e:
        return ToolResult(
            success=False,
            error=str(e),
            error_type="read_error",
        )

    if start_line < 1 or end_line < 0:
        return ToolResult(
            success=False,
            error="start_line must be >= 1 and end_line must be >= 0",
            error_type="invalid_range",
        )

    if end_line == 0:
        end_line = len(lines)
    if start_line > len(lines):
        if len(lines) == 0:
            # Empty file — reading with defaults (start_line=1, end_line=0/1)
            # should succeed with empty output.
            return ToolResult(success=True, output="")
        return ToolResult(
            success=False,
            error=f"start_line {start_line} exceeds file length {len(lines)}",
            error_type="invalid_range",
        )

    raw = "".join(lines[start_line - 1 : end_line])
    body, truncated = _truncate(raw, _MAX_READ_FILE_SAFETY_LIMIT, label="file content")

    # When truncated, add line-range metadata so the LLM can narrow its
    # next read to the missing portion.
    if truncated:
        actual_start = start_line
        actual_end = actual_start + body.count("\n")
        body += (
            f"\n[Read lines {actual_start}-{actual_end} of {len(lines)} total. "
            f"Use start_line/end_line to read the remaining portion.]"
        )

    return ToolResult(
        success=True,
        output=body,
        truncated=truncated,
    )


_strip_config_from_schema(read_file.params_json_schema)


# ---------------------------------------------------------------------------
# Summarizer
# ---------------------------------------------------------------------------


def summarize(args: dict, output: str) -> str | None:
    """Produce a one-line summary of a ``read_file`` call.

    Returns ``None`` if the call failed (nothing meaningful to
    summarise).
    """
    path = args.get("path", "?")
    lines = output.count("\n") + (1 if output.strip() else 0)
    purpose = _extract_purpose(output, file_path=path)
    return f"- {path} ({lines} lines): {purpose}"
