"""
copane CLI argument parsing and dispatch.

Handles command-line arguments, --list-models, --switch, --model-info,
and the initial query modes (--explain, --test, --review, --refactor).
"""

import argparse

from copane.tmux_agent import get_agent
from copane.term_styles import (
    Colors,
    get_bold,
    get_colored,
    get_success_message,
    get_warning_message,
    print_bold,
    print_colored,
    print_row,
    print_tuble,
    print_section_header,
    print_success,
    print_error,
    print_info,
    SEPARATOR,
    DOUBLE_SEPARATOR,
    STAR,
    ARROW_RIGHT,
)


# ── Brand constants ─────────────────────────────────────────────────────

APP_NAME = "copane"
APP_TAGLINE = "AI Coding Agent"
APP_VERSION = "1.0.0"


# ── Help examples ──────────────────────────────────────────────────────

help_examples = [
    get_colored("Examples:", Colors.ACCENT),
    get_colored(
        f"  {APP_NAME}{30*' '} {get_colored('— Interactive mode', Colors.RESET)}",
        Colors.PRIMARY,
    ),
    get_colored(f"  {APP_NAME} --mode explain --file main.py", Colors.PRIMARY),
    get_colored(
        f'  {APP_NAME} --mode test --text "def add(a,b): return a+b"',
        Colors.PRIMARY,
    ),
    get_colored(f"  {APP_NAME} --list-models", Colors.PRIMARY),
    get_colored(f"  {APP_NAME} --switch deepseek-chat", Colors.PRIMARY),
    get_colored(f"  {APP_NAME} --model-info", Colors.PRIMARY),
]


# ── Argument parser ──────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None):
    """Build and parse the argument parser."""
    parser = argparse.ArgumentParser(
        description=get_bold(f"{APP_NAME} — {APP_TAGLINE}"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(help_examples),
    )

    parser.add_argument(
        "--mode",
        choices=["explain", "test", "review", "refactor"],
        help="Quick action mode",
    )
    parser.add_argument("--file", help="File to operate on (used with --mode)")
    parser.add_argument(
        "--text", help="Direct text to operate on (overrides --file)"
    )
    parser.add_argument(
        "--no-banner", action="store_true", help="Skip the banner"
    )
    parser.add_argument(
        "--list-models", action="store_true", help="List models and exit"
    )
    parser.add_argument(
        "--switch", help="Switch to a different model and exit"
    )
    parser.add_argument(
        "--model-info", action="store_true", help="Show model info and exit"
    )
    parser.add_argument("--env-file", help="Path to .env file with API keys")
    return parser.parse_args(argv)


# ── CLI-only dispatch (exit after) ──────────────────────────────────────

def handle_args(args) -> bool:
    """Handle arguments that cause an immediate exit.

    Returns True if the caller should exit instead of starting the REPL.
    """
    agent = get_agent() 
    if args.list_models:
        print_model_list()
        return True
    if args.switch:
        try:
            agent.switch_model(args.switch)
            print_success(f"Switched to {args.switch}")
            print_model_info()
        except ValueError as e:
            print_error(str(e))
            print_model_list()
        return True
    if args.model_info:
        print_model_info()
        return True
    return False


# ── Model listing (display) ─────────────────────────────────────────────

def print_model_list():
    """Print a table of all available models."""
    agent = get_agent()
    models = agent.list_available_models()
    print_section_header(f"{STAR} Available Models", Colors.PRIMARY)

    print_row(
        ("Key", "Name", "Type", "Status", "Description"),
        colors=[Colors.BOLD, Colors.BOLD, Colors.BOLD, Colors.BOLD, Colors.BOLD],
        column_sizes=[20, 20, 10, 15, 0],
    )
    print_colored(SEPARATOR, Colors.SECONDARY)

    for key, info in models.items():
        status_color = (
            Colors.SUCCESS
            if info["status"] == "configured"
            else Colors.INFO
            if info["status"] == "available"
            else Colors.WARNING
            if info["status"] == "missing_api_key"
            else Colors.ERROR
        )
        sel = ARROW_RIGHT if info["is_selected"] else " "

        print_row(
            (f"{sel} {key}", info["name"], info["type"], info["status"], info["description"]),
            colors=[
                Colors.SUCCESS if info["is_selected"] else Colors.RESET,
                Colors.RESET,
                Colors.RESET,
                status_color,
                Colors.RESET,
            ],
            column_sizes=[20, 20, 10, 15, 0],
            left_pad="",
        )

    print(f"\n{Colors.INFO}Use /switch <model_key> to change.{Colors.RESET}")


def print_model_info():
    """Print details about the currently selected model."""
    agent = get_agent()
    mi = agent.get_model_info()

    def _color(item: str) -> str:
        if item not in ("status", "type", "API Key"):
            return Colors.RESET
        if item == "API Key":
            return Colors.SUCCESS if mi["env_key"] and __import__("os").getenv(mi["env_key"]) else Colors.WARNING
        return Colors.SUCCESS if mi[item] in ("configured", "available") else Colors.WARNING

    import os  # lazy import to avoid top-level side effects

    if mi["env_key"]:
        ak = os.getenv(mi["env_key"])
        if ak:
            mk = ak[:4] + "…" + ak[-4:] if len(ak) > 12 else "***"
            mi["API Key"] = mk
        else:
            mi["API Key"] = "Not set"
    else:
        mi["env_key"] = "N/A"

    print_section_header(f"{STAR} Current Model", Colors.ACCENT)

    for k, v in mi.items():
        print_tuble((f"{k.capitalize()}:", v), Colors.BOLD, _color(k), spacing="12")


# ── Initial query builder ───────────────────────────────────────────────

def build_initial_query(args) -> str | None:
    """Build the first AI prompt from --mode, --file, or --text.

    Returns None if no mode was given or if the file could not be read.
    """
    if not args.mode:
        return None

    content = _read_input(args)
    if content is None:
        return None

    prompts = {
        "explain": f"Please explain the following code:\n\n```\n{content}\n```",
        "test": f"Please write comprehensive unit tests for the following code:\n\n```\n{content}\n```",
        "review": f"Please review the following code and suggest improvements:\n\n```\n{content}\n```",
        "refactor": f"Please refactor the following code:\n\n```\n{content}\n```",
    }
    return prompts.get(args.mode, f"Regarding: {content}")


def _read_input(args) -> str | None:
    """Read content from --text or --file, printing status along the way."""
    if args.text:
        content = args.text
        print_info(f"Using provided text ({len(content)} chars)")
        return content

    if args.file:
        try:
            with open(args.file) as f:
                content = f.read()
            print_success(f"Loaded file: {args.file} ({len(content)} chars)")
            return content
        except FileNotFoundError:
            print_error(f"File not found: {args.file}")
        except Exception as e:
            print_error(f"Error reading {args.file}: {e}")
        return None

    print_error("--mode requires either --file or --text")
    return None
