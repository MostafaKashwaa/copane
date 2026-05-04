"""``get_current_dir`` — return the current working directory."""

import os

from agents import function_tool
from langsmith import traceable

from ._base import ToolResult, _strip_config_from_schema


@function_tool
@traceable(run_type="tool", name="Get Current Directory")
def get_current_dir() -> ToolResult:
    """Return the current working directory."""
    return ToolResult(
        success=True,
        output=os.getcwd(),
    )


_strip_config_from_schema(get_current_dir.params_json_schema)


# ---------------------------------------------------------------------------
# Summarizer
# ---------------------------------------------------------------------------


def summarize(args: dict, output: str) -> str | None:
    """``get_current_dir`` output is trivial — no summary needed."""
    return None
