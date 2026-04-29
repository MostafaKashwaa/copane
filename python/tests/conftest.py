"""Shared fixtures and helpers for copane tool tests."""

import json
import re
import os
import tempfile
from pathlib import Path

import pytest

from agents.tool import ToolContext
from copane import tools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(**overrides) -> ToolContext:
    """Build a minimal ToolContext that satisfies the SDK's requirements."""
    return ToolContext(
        context=overrides.get("context", None),
        tool_name=overrides.get("tool_name", "test_tool"),
        tool_call_id=overrides.get("tool_call_id", "call-test-001"),
        tool_arguments=overrides.get("tool_arguments", "{}"),
    )


async def invoke(tool, **kwargs) -> str:
    """Call a tool's `on_invoke_tool` with JSON-serialised kwargs.

    Returns the string result (which is a serialised ToolResult).
    """
    ctx = _ctx(tool_name=tool.name, tool_arguments=json.dumps(kwargs))
    raw = await tool.on_invoke_tool(ctx, json.dumps(kwargs))
    return raw


def parse_result(raw: str) -> tools.ToolResult:
    """Parse the tool's string output back into a ToolResult pydantic model.

    The string format is:
      "[Error: <type>] <msg>" for failures
      "<output>" for success (maybe with "[output truncated]" suffix)
    """
    if raw.startswith("[Error: "):
        match = re.match(r"^\[Error: (\w+)\] (.*)", raw)
        if match:
            return tools.ToolResult(
                success=False,
                error=match.group(2),
                error_type=match.group(1),
            )
    # Parse success output, checking for truncated marker
    truncated = raw.endswith("[output truncated]")
    if truncated:
        output = raw[: -len("[output truncated]")]
    else:
        output = raw
    return tools.ToolResult(success=True, output=output, truncated=truncated)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_dir():
    """Yield a temporary directory that is automatically cleaned up."""
    with tempfile.TemporaryDirectory() as d:
        old_cwd = os.getcwd()
        os.chdir(d)
        yield Path(d)
        os.chdir(old_cwd)


@pytest.fixture
def sample_file(tmp_dir):
    """Create a sample file with known content."""
    path = tmp_dir / "sample.txt"
    path.write_text("line1\nline2\nline3\nline4\nline5\n")
    return path
