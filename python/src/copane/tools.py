"""Tool definitions for the copane AI coding assistant.

Each tool is a @function_tool that the LLM can call during a conversation.
Write confirmation uses an async prompt from prompt_toolkit for terminal safety.
All tools return structured ToolResult objects for reliable LLM parsing.
"""

import os
import re
import sys
import difflib
import subprocess
from typing import Annotated
from agents import function_tool
from langsmith import traceable
from pydantic import BaseModel, Field
import shlex


# ---------------------------------------------------------------------------
# Structured result model
# ---------------------------------------------------------------------------


class ToolResult(BaseModel):
    """Structured return value for every tool.

    The LLM can inspect ``.success`` directly rather than parsing text,
    and uses ``.error_type`` to decide on a recovery strategy.
    """

    success: bool = Field(description="Whether the tool completed its intended operation.")
    output: str = Field(default="", description="Main text output (file contents, command output, matches, …).")
    error: str = Field(default="", description="Human-readable error description (empty on success).")
    error_type: str = Field(
        default="",
        description=(
            "Machine-readable label such as ``'file_not_found'``, ``'timeout'``, "
            "``'blocked_command'``, ``'write_cancelled'``, etc."
        ),
    )
    truncated: bool = Field(default=False, description="True when the output was clipped to fit the size limit.")

    def __str__(self) -> str:
        """Render as a compact text block the LLM can easily scan."""
        if not self.success:
            return f"[Error: {self.error_type}] {self.error}"
        parts = [self.output]
        if self.truncated:
            parts.append("[output truncated]")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Write-confirmation session (set by app.py at startup)
# ---------------------------------------------------------------------------

_confirm_session = None


def set_confirm_session(session):
    """Store the prompt session for write confirmation prompts.

    Called once during REPL initialisation in app.py.
    """
    global _confirm_session
    _confirm_session = session


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
    re.compile(r'\brm\s+-rf\s+[/~]', re.IGNORECASE),          # rm -rf /
    re.compile(r'\bdd\s+if=', re.IGNORECASE),                  # dd if=/dev/zero
    re.compile(r'>\s+/dev/', re.IGNORECASE),                    # > /dev/sda
    re.compile(r'\bmkfs\.', re.IGNORECASE),                     # mkfs.ext4
    re.compile(r':\(\)\s*\{'),                                   # fork bomb
    re.compile(r'\bchmod\s+-R\s+0{4}\b', re.IGNORECASE),        # chmod -R 0000 /
    re.compile(r'\bmv\s+[/~]\s+/dev/null\b', re.IGNORECASE),    # mv / /dev/null
]

_MAX_OUTPUT = 8_000
_MAX_GREP_OUTPUT = 5_000

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_dangerous(cmd: str) -> str | None:
    """Return a description if *cmd* looks destructive, else ``None``."""
    for pattern in _DANGEROUS_PATTERNS:
        m = pattern.search(cmd)
        if m:
            return m.group()
    return None


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


def _truncate(text: str, limit: int, label: str = "output") -> tuple[str, bool]:
    """Truncate *text* to *limit* characters.

    Returns ``(text, was_truncated)``.
    """
    if len(text) > limit:
        return f"{text[:limit]}\n[... {label} truncated to {limit} chars]", True
    return text, False


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@function_tool
@traceable(run_type="tool", name="Read File")
def read_file(
    path: Annotated[str, Field(description="Absolute or relative path to the file to read")],
    start_line: Annotated[int, Field(description="First line number to read (1-indexed)")] = 1,
    end_line: Annotated[int, Field(description="Last line number to read (0 means read to end of file)")] = 0,
) -> str:
    """Read a file or a line range from it. Use absolute or relative paths."""
    if not os.path.exists(path):
        return str(ToolResult(
            success=False,
            error=f"File not found: {path}",
            error_type="file_not_found",
        ))

    try:
        with open(path) as f:
            lines = f.readlines()
    except OSError as e:
        return str(ToolResult(
            success=False,
            error=str(e),
            error_type="read_error",
        ))

    if start_line < 1 or end_line < 0:
        return str(ToolResult(
            success=False,
            error="start_line must be >= 1 and end_line must be >= 0",
            error_type="invalid_range",
        ))

    if end_line == 0:
        end_line = len(lines)
    if start_line > len(lines):
        if len(lines) == 0:
            # Empty file — reading with defaults (start_line=1, end_line=0/1)
            # should succeed with empty output.
            return str(ToolResult(success=True, output=""))
        return str(ToolResult(
            success=False,
            error=f"start_line {start_line} exceeds file length {len(lines)}",
            error_type="invalid_range",
        ))

    return str(ToolResult(
        success=True,
        output="".join(lines[start_line - 1: end_line]),
    ))

# Strip the spurious "config" property injected by @traceable
_strip_config_from_schema(read_file.params_json_schema)


@function_tool
@traceable(run_type="tool", name="Run Command")
def run_command(
    cmd: Annotated[str, Field(description="Shell command to execute (destructive patterns are blocked)")],
) -> str:
    """Run a shell command and return stdout+stderr.

    Use for tests, builds, git, or any ad-hoc terminal task.
    Commands matching known destructive patterns are blocked.
    """
    dangerous = _is_dangerous(cmd)
    if dangerous:
        return str(ToolResult(
            success=False,
            error=(
                f"Command blocked — matched dangerous pattern {dangerous!r}. "
                "If you believe this is a false positive, ask the user to "
                "run it manually."
            ),
            error_type="blocked_command",
        ))

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return str(ToolResult(
            success=False,
            error="Command timed out after 30 seconds.",
            error_type="timeout",
        ))
    except FileNotFoundError:
        return str(ToolResult(
            success=False,
            error="Command not found.",
            error_type="command_not_found",
        ))
    except OSError as e:
        return str(ToolResult(
            success=False,
            error=str(e),
            error_type="os_error",
        ))

    output = result.stdout + result.stderr
    body, truncated = _truncate(output, _MAX_OUTPUT, label="output")
    return str(ToolResult(
        success=result.returncode == 0,
        output=f"[exit code: {result.returncode}]\n{body}",
        error="" if result.returncode == 0 else output,
        error_type="non_zero_exit" if result.returncode != 0 else "",
        truncated=truncated,
    ))

_strip_config_from_schema(run_command.params_json_schema)


@function_tool
@traceable(run_type="tool", name="Grep Files")
def grep_files(
    pattern: Annotated[str, Field(description="Regular expression pattern to search for")],
    path: Annotated[str, Field(description="Directory or file path to search in")] = ".",
    file_glob: Annotated[str, Field(description="Glob pattern to filter files (e.g. '*.py', '*.md')")] = "*",
) -> str:
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
        return str(ToolResult(
            success=False,
            error="Grep timed out after 10 seconds.",
            error_type="timeout",
        ))
    except OSError as e:
        return str(ToolResult(
            success=False,
            error=str(e),
            error_type="os_error",
        ))

    body = result.stdout
    if not body.strip():
        return str(ToolResult(
            success=False,
            error="No matches found.",
            error_type="no_matches",
        ))

    body, truncated = _truncate(body, _MAX_GREP_OUTPUT, label="output")
    return str(ToolResult(
        success=True,
        output=body,
        truncated=truncated,
    ))

_strip_config_from_schema(grep_files.params_json_schema)


@function_tool
@traceable(run_type="tool", name="List Files")
def list_files(
    path: Annotated[str, Field(description="Directory path to list")] = ".",
    depth: Annotated[int, Field(description="Maximum depth of directory traversal")] = 2,
) -> str:
    """List directory structure up to a certain depth."""
    # Validate the path exists early — find(1) exits 0 even for nonexistent paths
    if not os.path.exists(path):
        return str(ToolResult(
            success=False,
            error=f"Path not found: {path}",
            error_type="file_not_found",
        ))

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
        return str(ToolResult(
            success=False,
            error=str(e),
            error_type="os_error",
        ))

    return str(ToolResult(
        success=True,
        output=result.stdout or "(empty directory)",
    ))

_strip_config_from_schema(list_files.params_json_schema)


@function_tool
@traceable(run_type="tool", name="Get Current Directory")
def get_current_dir() -> str:
    """Return the current working directory."""
    return str(ToolResult(
        success=True,
        output=os.getcwd(),
    ))

_strip_config_from_schema(get_current_dir.params_json_schema)


@function_tool
@traceable(run_type="tool", name="Write File")
async def write_file(
    path: Annotated[str, Field(description="Absolute or relative path of the file to write")],
    content: Annotated[str, Field(description="Full text content to write to the file")],
) -> str:
    """Write content to a file. Shows a diff preview and asks the user to confirm.

    Supports *y* (yes), *n* (no), and *a* (always allow for the rest of
    this session).
    """
    diff = _format_diff(path, content)

    # Write the diff to stderr so it doesn't interleave with the LLM's
    # streamed text on stdout.  Also emit a visual separator so the
    # confirmation request stands out clearly.
    print(f"\n{'-'*60}", file=sys.stderr)
    print(f"[write_file] {path} ({len(content)} chars)", file=sys.stderr)
    print("-" * 60, file=sys.stderr)
    print(diff, file=sys.stderr)
    print("-" * 60, file=sys.stderr)

    global _confirm_session
    if _confirm_session is not None:
        # Use the dedicated confirmation session rather than the main REPL
        # session.  The REPL session has multiline=True, mouse_support=True,
        # and a file completer – all inappropriate for a simple y/n prompt.
        # Those settings cause prompt_toolkit to manipulate the terminal in
        # ways that corrupt the streamed LLM output displayed above the
        # prompt, leading to overwritten / lost text in the scrollback.
        # from copane.tools import _get_confirm_prompt_session
        confirm_session = _get_confirm_prompt_session()
        confirm = (
                await confirm_session.prompt_async("Confirm write? (y/n/a): ")
                ).strip().lower()
    else:
        confirm = input("Confirm write? (y/n/a): ").strip().lower()

    if confirm in ("y", "a"):
        # Create parent directories if they don't exist
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        suffix = " (always-allowed for session)" if confirm == "a" else ""
        return str(ToolResult(
            success=True,
            output=f"Wrote {len(content)} chars to {path}{suffix}",
        ))

    return str(ToolResult(
        success=False,
        error="Write cancelled by user.",
        error_type="write_cancelled",
    ))

_strip_config_from_schema(write_file.params_json_schema)


# ---------------------------------------------------------------------------
# Dedicated confirmation prompt session (lazily created)
# ---------------------------------------------------------------------------

_confirm_prompt_session = None


def _get_confirm_prompt_session():
    """Return a minimal PromptSession suitable for y/n confirmations.

    This session deliberately avoids multiline, mouse support, file
    completion, and custom key bindings – it's a plain single-line
    prompt where Enter submits.  Using the main REPL session
    (which has multiline=True, mouse_support=True, etc.) during
    streaming corrupts the terminal state and causes the LLM's
    streamed text to be overwritten.
    """
    global _confirm_prompt_session
    if _confirm_prompt_session is None:
        from prompt_toolkit import PromptSession
        _confirm_prompt_session = PromptSession(
            multiline=False,
            mouse_support=False,
            complete_while_typing=False,
        )
    return _confirm_prompt_session
