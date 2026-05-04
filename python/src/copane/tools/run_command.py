"""``run_command`` — execute a shell command and return its output.

Destructive commands are blocked via regex heuristics.
"""

import subprocess
from typing import Annotated

from agents import function_tool
from langsmith import traceable
from pydantic import Field

from ._base import (
    ToolResult,
    _MAX_OUTPUT,
    _is_dangerous,
    _strip_config_from_schema,
    _truncate,
)


@function_tool
@traceable(run_type="tool", name="Run Command")
def run_command(
    cmd: Annotated[str, Field(description="Shell command to execute (destructive patterns are blocked)")],
) -> ToolResult:
    """Run a shell command and return stdout+stderr.

    Use for tests, builds, git, or any ad-hoc terminal task.
    Commands matching known destructive patterns are blocked.
    """
    dangerous = _is_dangerous(cmd)
    if dangerous:
        return ToolResult(
            success=False,
            error=(
                f"Command blocked — matched dangerous pattern {dangerous!r}. "
                "If you believe this is a false positive, ask the user to "
                "run it manually."
            ),
            error_type="blocked_command",
        )

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            success=False,
            error="Command timed out after 30 seconds.",
            error_type="timeout",
        )
    except FileNotFoundError:
        return ToolResult(
            success=False,
            error="Command not found.",
            error_type="command_not_found",
        )
    except OSError as e:
        return ToolResult(
            success=False,
            error=str(e),
            error_type="os_error",
        )

    output = result.stdout + result.stderr
    body, truncated = _truncate(output, _MAX_OUTPUT, label="output")
    return ToolResult(
        success=result.returncode == 0,
        output=f"[exit code: {result.returncode}]\n{body}",
        error="" if result.returncode == 0 else output,
        error_type="non_zero_exit" if result.returncode != 0 else "",
        truncated=truncated,
    )


_strip_config_from_schema(run_command.params_json_schema)


# ---------------------------------------------------------------------------
# Summarizer
# ---------------------------------------------------------------------------

# Number of chars of command output to include in the summary preview.
_SUMMARY_OUTPUT_PREVIEW = 200


def summarize(args: dict, output: str) -> str | None:
    """Produce a one-line summary of a ``run_command`` call."""
    cmd = args.get("cmd", "?")
    # Extract exit code from the output
    exit_code = "?"
    if output.startswith("[exit code:"):
        m_end = output.find("]")
        if m_end != -1:
            exit_code = output[12:m_end].strip()
            output_body = output[m_end + 1:].strip()
        else:
            output_body = output
    else:
        output_body = output

    # Preview: first _SUMMARY_OUTPUT_PREVIEW chars
    output_preview = output_body[:_SUMMARY_OUTPUT_PREVIEW].replace("\n", " ")
    if len(output_body) > _SUMMARY_OUTPUT_PREVIEW:
        output_preview += "…"

    return f"- {cmd} → exit {exit_code}: {output_preview}"
