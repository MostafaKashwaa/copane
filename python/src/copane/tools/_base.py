"""Shared utilities and models for copane tools.

This module contains the pieces that are used across multiple tools:
the ToolResult model, output truncation, schema helpers, danger
heuristics for shell commands, and diff formatting.
"""

import difflib
import os
import re
from typing import Annotated

from agents import function_tool
from langsmith import traceable
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Structured result model
# ---------------------------------------------------------------------------


class ToolResult(BaseModel):
    """Structured return value for every tool.

    The LLM can inspect ``.success`` directly rather than parsing text,
    and uses ``.error_type`` to decide on a recovery strategy.
    """

    success: bool = Field(
        description="Whether the tool completed its intended operation.")
    output: str = Field(
        default="", description="Main text output (file contents, command output, matches, …).")
    error: str = Field(
        default="", description="Human-readable error description (empty on success).")
    error_type: str = Field(
        default="",
        description=(
            "Machine-readable label such as ``'file_not_found'``, ``'timeout'``, "
            "``'blocked_command'``, ``'write_cancelled'``, etc."
        ),
    )
    truncated: bool = Field(
        default=False, description="True when the output was clipped to fit the size limit.")

    def __str__(self) -> str:
        """Render as a compact text block the LLM can easily scan."""
        if not self.success:
            return f"[Error: {self.error_type}] {self.error}"
        parts = [self.output]
        if self.truncated:
            parts.append("[output truncated]")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------


def _strip_config_from_schema(schema: dict) -> dict:
    """Remove the ``config`` property that ``@traceable`` injects into
    function signatures.

    ``@langsmith.traceable`` adds a keyword-only ``config`` parameter to
    every wrapped function.  When ``@function_tool`` subsequently builds
    a JSON schema from that signature, the ``config`` parameter ends up
    as a property with **no ``type`` key**, which is invalid for OpenAI's
    API (OpenAI requires every property to have a ``type``).  Removing it
    from the schema fixes the 400 error for OpenAI-based models.

    This function mutates the schema *in-place* for simplicity and also
    returns it.
    """
    props = schema.get("properties", {})
    if "config" in props:
        del props["config"]
    required = schema.get("required", [])
    if "config" in required:
        required.remove("config")
    return schema


# ---------------------------------------------------------------------------
# Danger heuristics for shell commands
# ---------------------------------------------------------------------------

_DANGEROUS_PATTERNS = [
    re.compile(r'\brm\s+-rf\s+[/~]', re.IGNORECASE),      # rm -rf /
    re.compile(r'\bdd\s+if=', re.IGNORECASE),             # dd if=/dev/zero
    re.compile(r'>\s+/dev/', re.IGNORECASE),              # > /dev/sda
    re.compile(r'\bmkfs\.', re.IGNORECASE),               # mkfs.ext4
    re.compile(r':\(\)\s*\{'),                                   # fork bomb
    re.compile(r'\bchmod\s+-R\s+0{4}\b', re.IGNORECASE),  # chmod -R 0000 /
    re.compile(r'\bmv\s+[/~]\s+/dev/null\b',
               re.IGNORECASE),                                     # mv / /dev/null
]

_MAX_OUTPUT = 8_000
_MAX_GREP_OUTPUT = 5_000

# Safety-net file-size cap.  Every reasonable source file fits within
# 50 KB.  Anything larger (minified JS, binary files mistakenly read
# as text) is truncated and the LLM is told to narrow its read with
# start_line/end_line or grep to narrow down.  This is a circuit
# breaker, not flow control — turn-boundary summarization in
# tmux_agent.py is the primary memory strategy.
_MAX_READ_FILE_SAFETY_LIMIT = 50_000


def _is_dangerous(cmd: str) -> str | None:
    """Return a description if *cmd* looks destructive, else ``None``."""
    for pattern in _DANGEROUS_PATTERNS:
        m = pattern.search(cmd)
        if m:
            return m.group()
    return None


# ---------------------------------------------------------------------------
# Diff formatting
# ---------------------------------------------------------------------------


def _format_diff(path: str, new_content: str) -> str:
    """Build a unified diff, or show full content for a new file."""
    if os.path.exists(path):
        with open(path) as f:
            old_content = f.read()
        diff = difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
        return "".join(diff)
    return f"(new file)\n---\n{new_content}\n---"


# ---------------------------------------------------------------------------
# Output truncation
# ---------------------------------------------------------------------------


def _truncate(text: str, limit: int, label: str = "output") -> tuple[str, bool]:
    """Truncate *text* to *limit* characters.

    Returns ``(text, was_truncated)``.
    """
    if len(text) > limit:
        return f"{text[:limit]}\n[... {label} truncated to {limit} chars]", True
    return text, False
