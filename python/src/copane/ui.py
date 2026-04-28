"""
copane UI — banner, model info, streaming output, and query builder.

All terminal presentation logic that depends on the agent state.
"""

import os
import sys
from datetime import datetime

from copane.tmux_agent import get_agent
from copane.term_styles import (
    Colors,
    LOGO,
    LOGO_ONELINER,
    get_bold,
    get_colored,
    get_success_message,
    get_warning_message,
    print_bold,
    print_colored,
    print_dim,
    print_success,
    print_error,
    print_warning,
    print_info,
    print_row,
    print_tuble,
    print_section_header,
    SEPARATOR,
    DOUBLE_SEPARATOR,
    STAR,
    BULLET,
)


# ── Constants ───────────────────────────────────────────────────────────

APP_NAME = "copane"

# Coloured logo for the banner
LOGO_DISPLAY = get_bold(LOGO, Colors.PRIMARY)

# Colours used by the streamed response
THINKING_DOTS = f"{Colors.INFO}Thinking{Colors.RESET}"


# ── Banners ─────────────────────────────────────────────────────────────

def print_banner():
    """Professional startup banner with system info."""
    agent = get_agent()
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    print("\033[2J\033[H", end="")
    print(LOGO_DISPLAY)

    info_lines = {
        "Version": "1.0.0",  # TODO: read from package metadata
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
        get_success_message("DeepSeek") if deepseek_key else get_warning_message("DeepSeek")
    )
    api_parts.append(
        get_success_message("OpenAI") if openai_key else get_warning_message("OpenAI")
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


# ── Streaming output ────────────────────────────────────────────────────

async def print_streamed_response(stream_generator):
    """Print a streaming AI response chunk by chunk in the terminal.

    Handles KeyboardInterrupt and general exceptions gracefully.
    """
    agent = get_agent()
    print(f"\n{THINKING_DOTS}", end="", flush=True)

    try:
        text = ""
        async for chunk in stream_generator:
            print(chunk, end="", flush=True)
            text += chunk
        print("\n", flush=True)
        print_row(
            ("", "", f"({agent.get_message_count()}) message/s in history"),
            colors=[Colors.RESET, Colors.RESET, Colors.INFO],
            column_sizes=[0, 7, 0],
        )
        print_success(f"Response complete ({len(text)} chars)")

    except KeyboardInterrupt:
        print_warning("\n\n[Interrupted]\n", "")
    except Exception as e:
        print_error(f"Response error: {e}")
