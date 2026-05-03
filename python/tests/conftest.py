"""Shared fixtures and helpers for copane tool tests."""

import json
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


async def invoke(tool, **kwargs) -> tools.ToolResult:
    """Call a tool's `on_invoke_tool` with JSON-serialised kwargs.

    Returns the ToolResult object directly (tools now return the Pydantic
    model rather than its string representation).
    """
    ctx = _ctx(tool_name=tool.name, tool_arguments=json.dumps(kwargs))
    raw = await tool.on_invoke_tool(ctx, json.dumps(kwargs))
    return raw


def parse_result(raw: tools.ToolResult) -> tools.ToolResult:
    """Pass-through for backward compatibility — tools now return ToolResult directly.

    Previously tools returned a string representation and this function
    parsed it back.  Now tools return ToolResult objects, so this is a
    no-op.  Kept so existing test code using ``parse_result()`` still
    compiles, but new tests can just use the result directly.
    """
    return raw


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
