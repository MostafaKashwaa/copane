"""
copane UI — banner, model info, streaming output, and query builder.

All terminal presentation logic that depends on the agent state.
"""

import os
import sys
from datetime import datetime

from copane._version import get_version
from copane.tmux_agent import get_agent
from copane.term_styles import (
    Colors,
    LOGO,
    LOGO_ONELINER,
    get_bold,
    get_colored,
    get_dim,
    get_success_message,
    get_warning_message,
    print_bold,
    print_colored,
    print_success,
    print_error,
    print_warning,
    print_row,
    print_tuble,
    DOUBLE_SEPARATOR,
    STAR,
    BULLET,
)
from copane.preview import format_tool_preview
from copane.renderers import Renderer, RawRenderer
from prompt_toolkit import PromptSession

from copane.tools import ToolResult


# ── Constants ───────────────────────────────────────────────────────────

APP_NAME = "copane"

# Coloured logo for the banner
LOGO_DISPLAY = get_bold(LOGO, Colors.PRIMARY)

# Colours used by the streamed response
THINKING_DOTS = f"{Colors.INFO}Thinking{Colors.RESET}"


# ── Tool approval prompt session  ─────────────────────────────────────

_approval_prompt_session: PromptSession | None = None


def _get_approval_prompt_session() -> PromptSession:
    """Return a minimal PromptSession for yes/no approval prompts.

    Avoids multiline, mouse support, and file completion — just a
    simple single-line prompt that Enter submits.
    """
    global _approval_prompt_session
    if _approval_prompt_session is None:
        _approval_prompt_session = PromptSession(
            multiline=False,
            mouse_support=False,
            complete_while_typing=False,
        )
    return _approval_prompt_session


async def _approval_prompt() -> str:
    """Ask the user to approve or reject a tool call.

    Returns one of: 'y', 'n', 'a', 'r', 'q'.
    """
    session = _get_approval_prompt_session()
    while True:
        answer = (
            await session.prompt_async(
                "Approve? (y)es / (n)o / (a)lways / neve(r) / (q)uit: "
            )
        ).strip().lower()
        if answer in ('y', 'n', 'a', 'r', 'q'):
            return answer
        print("  Invalid choice. Try again.", file=sys.stderr, flush=True)


# ── Banners ─────────────────────────────────────────────────────────────

def print_banner():
    """Professional startup banner with system info."""
    agent = get_agent()
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    print("\033[2J\033[H", end="")
    print(LOGO_DISPLAY)

    info_lines = {
        "Version": get_version(),
        "Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Python": sys.version.split()[0],
        "Terminal": os.getenv("TERM", "unknown"),
    }

    print_colored(DOUBLE_SEPARATOR, Colors.SECONDARY)
    for k, v in info_lines.items():
        print_row(
            (f"{k}:", v),
            colors=[Colors.INFO + Colors.BOLD, Colors.RESET],
            column_sizes=[10, 0],
        )
    print_colored(DOUBLE_SEPARATOR, Colors.SECONDARY)

    # Model and API status
    print_bold("Status:")
    model_info = agent.get_model_info()
    model_color = (
        Colors.SUCCESS
        if model_info["status"] in ("configured", "available")
        else Colors.WARNING
    )

    print_row(
        (BULLET, "Model:", model_info["description"]),
        colors=[Colors.RESET, Colors.RESET, model_color],
        column_sizes=[0, 7, 0],
        decorations=["", "", Colors.BOLD],
    )
    print_row(
        ("", "", f'{model_info["type"]}', f"· {model_info['status']}"),
        colors=[Colors.RESET, Colors.RESET, Colors.INFO, model_color],
        column_sizes=[0, 7, 0, 0],
    )

    api_parts = []
    api_parts.append(
        get_success_message(
            "DeepSeek") if deepseek_key else get_warning_message("DeepSeek")
    )
    api_parts.append(
        get_success_message(
            "OpenAI") if openai_key else get_warning_message("OpenAI")
    )

    print_row(
        (BULLET, "APIs:", " | ".join(api_parts)),
        colors=[Colors.RESET, Colors.RESET, Colors.INFO],
        column_sizes=[0, 7, 0],
    )

    cwd = os.getcwd()
    if len(cwd) > 50:
        cwd = "…" + cwd[-48:]
    print_row(
        (BULLET, "Dir:", cwd),
        colors=[Colors.RESET, Colors.RESET, Colors.ACCENT],
        column_sizes=[0, 7, 0],
    )

    _print_quick_commands()

    print_colored(DOUBLE_SEPARATOR, Colors.SECONDARY)
    print_bold(f"{STAR} {APP_NAME} is ready. Ask away!\n", Colors.SUCCESS)


def _print_quick_commands():
    """Print the quick-reference command list."""
    commands = [
        ("@file", "Include file content"),
        ("/models", "List models"),
        ("/switch <key>", "Switch model"),
        ("exit / quit", "Quit"),
        ("Ctrl-C", "Cancel"),
        ("Tab", "Auto-complete file"),
    ]
    print_bold("\nCommands:")
    for cmd, desc in commands:
        print_tuble((cmd, desc), Colors.PRIMARY, Colors.RESET, spacing="15")


def print_no_banner():
    """Minimal startup for embedding in other tools."""
    print_colored(f"{LOGO_ONELINER}\n", Colors.PRIMARY)
    print_success(f"{APP_NAME} ready. Ask away!\n", f"{STAR} ")


# ── Tool output helpers ────────────────────────────────────────────────

def _format_tool_output(res: ToolResult) -> str:
    """Return a compact one-liner status icon + first-line preview.

    The result always starts with `` ✓`` (success) or `` ✗`` (failure).
    """
    if isinstance(res, str):
        # Legacy support for tools that return raw strings instead of ToolResult
        output = res.strip()
        if output.startswith("[exit code: 0]"):
            line0 = output.splitlines()[0] if output else ""
            return f" ✓ {line0} "
        elif output.startswith("[Error:") or output.startswith("[exit code:"):
            line0 = output.splitlines()[0] if output else ""
            return f" ✗ {line0} "
        elif output.startswith("Wrote "):
            return f" ✓ ({output})"
        elif output:
            line0 = output.splitlines()[0]
            return f" ✓ {line0} "
        else:
            return " ✓ "
    if res.success:
        if res.output.strip():
            line0 = res.output.splitlines()[0]
            return f" ✓ {line0} "
        else:
            return " ✓ "
    else:
        error_text = res.error.splitlines()[0].strip(
        ) if res.error else res.output.splitlines()[0].strip()
        return f" ✗ {error_text} "


# ── Streaming output ────────────────────────────────────────────────────

async def print_streamed_response(stream_generator, renderer: Renderer | None = None):
    """Print a streaming AI response chunk by chunk in the terminal.

    Handles KeyboardInterrupt and general exceptions gracefully.

    *renderer* controls how thinking and text chunks are displayed.
    Pass ``None`` to use the default (RawRenderer, no markdown).
    Tool calls, tool responses, and approval are handled by this
    function directly — they do not vary between renderers.
    """
    if renderer is None:
        renderer = RawRenderer()

    agent = get_agent()

    # Track the actual plain-text length (without ANSI codes) for the summary
    plain_text_len = 0

    try:
        renderer.on_response_begin()
        tool_lines = {}

        async for kind, chunk in stream_generator:
            match kind:
                case 'thinking':
                    renderer.on_thinking_chunk(chunk)
                    plain_text_len += len(chunk)

                case 'text':
                    renderer.on_text_chunk(chunk)
                    plain_text_len += len(chunk)

                case 'tool_call':
                    tool_name, tool_id = chunk
                    # renderer.on_interrupt()
                    # print(
                    #     f"\n{get_colored(f'🔧 [{tool_name}]', Colors.ACCENT)}",
                    #     end=" ", flush=True,
                    # )
                    renderer.on_tool_call_chunk(chunk)
                    # tool_lines[tool_id] = f"\n{get_colored(f'🔧 [{tool_name}]', Colors.ACCENT)}"

                    # approximate: icon + brackets
                    plain_text_len += len(chunk) + 5

                case 'tool_response':
                    output, call_id = chunk
                    result = _format_tool_output(output)
                    # renderer.on_interrupt()
                    renderer.on_tool_response_chunk(chunk)
                    
                    # if isinstance(output, ToolResult):
                    #     color = Colors.SUCCESS if output.success else Colors.ERROR
                    #     plain_text_len += len(output.output)
                    # else:
                    #     color = Colors.INFO
                    #     plain_text_len += len(output)
                    # print(
                    #     f"{tool_lines.pop(call_id, '\n')}\n\t{get_colored(result.strip(), color)}",
                    #     end="\n",
                    #     flush=True
                    # )

                    # print(tool_lines.pop(call_id, "\n") \
                    # + get_colored(result.strip(), color),
                    # end="\n", flush=True)
                    # print(f"{get_colored(result.strip(), color)}",
                    # end="\n", flush=True)

                case 'tool_approval':
                    item, state = chunk
                    tool_name = item.tool_name or 'unknown tool'
                    renderer.on_interrupt()

                    preview = format_tool_preview(item)
                    print(f"\n{get_colored(f'─' * 60, Colors.WARNING)}")
                    print(
                        f"{get_colored(f'⚠ Approval needed: {tool_name}', Colors.WARNING)}")
                    print(f"{get_colored(f'─' * 60, Colors.WARNING)}")
                    print(preview, end="", flush=True)
                    print(f"\n{get_colored(f'─' * 60, Colors.WARNING)}")

                    decision = await _approval_prompt()

                    if decision == 'q':
                        print_warning("\n[Response cancelled by user]\n")
                        return

                    agent.handle_tool_approval(item, decision, state)

                case _:
                    # Unknown event kind — pass through as text
                    renderer.on_text_chunk(str(chunk))
                    plain_text_len += len(str(chunk))

        renderer.on_response_complete()

        print("\n", flush=True)
        print_row(
            ("", "", f"({agent.get_message_count()}) message/s in history"),
            colors=[Colors.RESET, Colors.RESET, Colors.INFO],
            column_sizes=[0, 7, 0],
        )
        print_success(f"Response complete ({plain_text_len} chars)")

    except KeyboardInterrupt:
        print_warning("\n\n[Interrupted]\n", "")
    except Exception as e:
        print_error(f"Response error: {e}")
