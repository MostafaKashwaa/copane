"""copane tools package.

Each tool lives in its own submodule.  Every submodule exports:

*   ``tool`` — the decorated ``@function_tool`` callable
*   ``summarize(args, output) -> str | None`` — turn-boundary summarizer

This ``__init__.py`` re-exports everything so existing imports from
``copane.tools`` continue to work unchanged.
"""

# ── Shared utilities ──────────────────────────────────────────────────
from ._base import (
    ToolResult,
    _format_diff,
    _is_dangerous,
    _truncate,
)
from ._base import _strip_config_from_schema  # re-export for test_schema

# ── Tools ─────────────────────────────────────────────────────────────
from .edit_file import edit_file, summarize as _sum_edit
from .get_current_dir import get_current_dir, summarize as _sum_getcwd
from .grep_files import grep_files, summarize as _sum_grep
from .list_files import list_files, summarize as _sum_ls
from .read_file import read_file, summarize as _sum_read
from .run_command import run_command, summarize as _sum_cmd
from .web_search import web_search, summarize as _sum_web
from .write_file import write_file, summarize as _sum_write

# ── Lookup table for the agent's dispatch loop ────────────────────────
TOOL_SUMMARIZERS: dict[str, "function"] = {
    "edit_file": _sum_edit,
    "read_file": _sum_read,
    "run_command": _sum_cmd,
    "grep_files": _sum_grep,
    "list_files": _sum_ls,
    "get_current_dir": _sum_getcwd,
    "web_search": _sum_web,
    "write_file": _sum_write,
}
