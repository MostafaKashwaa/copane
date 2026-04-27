#!/usr/bin/env python3
"""
copane — AI Coding Agent for Vim + Tmux
Multi-model, file-aware, terminal-first.
"""

import os
import asyncio
import argparse
import sys
from datetime import datetime

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from dotenv import load_dotenv
from prompt_toolkit.key_binding.key_bindings import KeyBindings
from copane.tmux_agent import agent
from copane.term_styles import (
    ansi_bold,
    Colors,
    LOGO,
    LOGO_COMPACT,
    LOGO_ONELINER,
    ansi_warn,
    get_bold,
    get_colored,
    get_success_message,
    get_warning_message,
    print_bold,
    print_colored,
    print_dim,
    print_success,
    print_error,
    print_row,
    print_tuble,
    print_warning,
    print_info,
    print_section_header,
    SEPARATOR,
    DOUBLE_SEPARATOR,
    STAR,
    BULLET,
    ARROW_RIGHT,
)

from copane.file_utils import FileCompleter, expand_files


# ── Environment loading ─────────────────────────────────────────────────

def load_env_file(env_path: str | None = None):
    """
    Load the .env file from the given path, or fall back to local .env.

    The path is also stored in COPANE_ENV_FILE so that submodules (e.g.
    tmux_agent) can re-read it if needed.
    """
    path = env_path or os.environ.get("COPANE_ENV_FILE") or ".env"
    load_dotenv(dotenv_path=path, override=True)
    os.environ.setdefault("COPANE_ENV_FILE", os.path.abspath(path))


# ── Brand-configurable constants ────────────────────────────────────────

APP_NAME = "copane"
APP_TAGLINE = "AI Coding Agent"
APP_VERSION = "1.0.0"

# PROMPT_SYMBOL = ansi_print_bold(f"» ")
PROMPT_SYMBOL = ansi_bold(f"{3*ARROW_RIGHT} ")
EXIT_MESSAGE = get_colored(f"{STAR} {APP_NAME} — goodbye!", Colors.SUCCESS)
EXIT_COMMANDS = {"exit", "quit", "q"}
CONTINUATION_PROMPT = ARROW_RIGHT
CONTINUATION_COLOR = Colors.DIM


# Wrap the raw logo with colour
LOGO_DISPLAY = get_bold(LOGO, Colors.PRIMARY)


def print_banner():
    """Professional startup banner with system info."""
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    print("\033[2J\033[H", end="")

    print(LOGO_DISPLAY)

    info_lines = {
        "Version": APP_VERSION,
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
    model_color = Colors.SUCCESS if model_info["status"] in [
        "configured", "available"] else Colors.WARNING

    print_row(
        (BULLET, "Model:", model_info['description']),
        colors=[Colors.RESET, Colors.RESET, model_color],
        column_sizes=[0, 7, 0],
        decorations=['', '', Colors.BOLD]
    )
    print_row(
        ('', '', f'{model_info['type']}', f'· {model_info['status']}'),
        colors=[Colors.RESET, Colors.RESET, Colors.INFO, model_color],
        column_sizes=[0, 7, 0, 0],
    )

    api_parts = []
    if deepseek_key:
        api_parts.append(get_success_message("DeepSeek"))
    else:
        api_parts.append(get_warning_message("DeepSeek"))
    if OPENAI_API_KEY:
        api_parts.append(get_success_message("OpenAI"))
    else:
        api_parts.append(get_warning_message("OpenAI"))

    print_row(
        (BULLET, "APIs:", ' | '.join(api_parts)),
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

    # Quick commands
    commands = [
        ("@file", "Include file content"),
        ("/models", "List models"),
        ("/switch <key>", "Switch model"),
        ("exit / quit", "Quit"),
        ("Ctrl-C", "Cancel"),
        ("Tab", "Auto-complete file"),
    ]
    print_bold('\nCommands:')
    for cmd, desc in commands:
        print_tuble((cmd, desc), Colors.PRIMARY, Colors.RESET, spacing="15")

    print_colored(DOUBLE_SEPARATOR, Colors.SECONDARY)
    print_bold(f"{STAR} {APP_NAME} is ready. Ask away!\n", Colors.SUCCESS)


def print_no_banner():
    """Minimal startup (for embedding in other tools)."""
    print_colored(f'{LOGO_ONELINER}\n', Colors.PRIMARY)
    print_success(f"{APP_NAME} ready. Ask away!\n", f'{STAR} ')


# ── Argument parser ──────────────────────────────────────────────────────
help_examples = [
    get_colored("Examples:", Colors.ACCENT),
    get_colored(
        f"  {APP_NAME}{30*' '} {get_colored('— Interactive mode', Colors.RESET)}", Colors.PRIMARY),
    get_colored(f"  {APP_NAME} --mode explain --file main.py", Colors.PRIMARY),
    get_colored(
        f"  {APP_NAME} --mode test --text \"def add(a,b): return a+b\"", Colors.PRIMARY),
    get_colored(f"  {APP_NAME} --list-models", Colors.PRIMARY),
    get_colored(f"  {APP_NAME} --switch deepseek-chat", Colors.PRIMARY),
    get_colored(f"  {APP_NAME} --model-info", Colors.PRIMARY),
]


def parse_args():
    parser = argparse.ArgumentParser(
        description=get_bold(f"{APP_NAME} — {APP_TAGLINE}"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(help_examples)
    )

    parser.add_argument("--mode", choices=["explain", "test", "review", "refactor"],
                        help="Quick action mode")
    parser.add_argument("--file", help="File to operate on (used with --mode)")
    parser.add_argument(
        "--text", help="Direct text to operate on (overrides --file)")
    parser.add_argument("--no-banner", action="store_true",
                        help="Skip the banner")
    parser.add_argument("--list-models", action="store_true",
                        help="List models and exit")
    parser.add_argument(
        "--switch", help="Switch to a different model and exit")
    parser.add_argument("--model-info", action="store_true",
                        help="Show model info and exit")
    parser.add_argument("--env-file", help="Path to .env file with API keys")
    return parser.parse_args()


# ── Initial query builder ────────────────────────────────────────────────

def build_initial_query(args):
    if not args.mode:
        return None

    content = None
    if args.text:
        content = args.text
        print_info(f"Using provided text ({len(content)} chars)")
    elif args.file:
        try:
            with open(args.file) as f:
                content = f.read()
            print_success(f"Loaded file: {args.file} ({len(content)} chars)")
        except FileNotFoundError:
            print_error(f"File not found: {args.file}")
            return None
        except Exception as e:
            print_error(f"Error reading {args.file}: {e}")
            return None
    else:
        print_error("--mode requires either --file or --text")
        return None

    mode_titles = {"explain": "Code Explanation", "test": "Test Generation",
                   "review": "Code Review", "refactor": "Code Refactoring"}
    title = mode_titles.get(args.mode, args.mode.title())
    print_section_header(f"{STAR} Starting {title}", Colors.ACCENT)

    prompts = {
        "explain": f"Please explain the following code:\n\n```\n{content}\n```",
        "test": f"Please write comprehensive unit tests for the following code:\n\n```\n{content}\n```",
        "review": f"Please review the following code and suggest improvements:\n\n```\n{content}\n```",
        "refactor": f"Please refactor the following code:\n\n```\n{content}\n```",
    }
    return prompts.get(args.mode, f"Regarding: {content}")


# ── Model listing ────────────────────────────────────────────────────────

def print_model_list():
    models = agent.list_available_models()
    print_section_header(f"{STAR} Available Models", Colors.PRIMARY)

    print_row(
        ("Key", "Name", "Type", "Status", "Description"),
        colors=[Colors.BOLD, Colors.BOLD,
                Colors.BOLD, Colors.BOLD, Colors.BOLD],
        column_sizes=[20, 20, 10, 15, 0],
    )
    print_colored(SEPARATOR, Colors.SECONDARY)

    for key, info in models.items():
        status_color = (Colors.SUCCESS if info["status"] == "configured"
                        else Colors.INFO if info["status"] == "available"
                        else Colors.WARNING if info["status"] == "missing_api_key"
                        else Colors.ERROR)
        sel = ARROW_RIGHT if info["is_selected"] else " "

        print_row(
            (
                f"{sel} {key}",
                info["name"],
                info["type"],
                info["status"],
                info["description"]
            ),
            colors=[
                Colors.SUCCESS if info["is_selected"] else Colors.RESET,
                Colors.RESET,
                Colors.RESET,
                status_color,
                Colors.RESET
            ],
            column_sizes=[20, 20, 10, 15, 0],
            left_pad=""
        )

    print(f"\n{Colors.INFO}Use /switch <model_key> to change.{Colors.RESET}")


def print_model_info():
    mi = agent.get_model_info()

    def get_color(item):
        if item not in ("status", "type", "API Key"):
            return Colors.RESET
        if item == "API Key":
            return Colors.SUCCESS if mi["env_key"] and os.getenv(mi["env_key"]) else Colors.WARNING
        return Colors.SUCCESS if mi[item] in ("configured", "available") else Colors.WARNING

    if mi["env_key"]:
        ak = os.getenv(mi["env_key"])
        if ak:
            mk = ak[:4] + "…" + ak[-4:] if len(ak) > 12 else "***"
            mi["API Key"] = mk
        else:
            mi["API Key"] = "Not set"
    else:
        mi["env_key"] = 'N/A'

    print_section_header(f"{STAR} Current Model", Colors.ACCENT)

    for k, v in mi.items():
        print_tuble(
            (f"{k.capitalize()}:", v),
            Colors.BOLD,
            get_color(k),
            spacing="12"
        )


# ── Streaming helpers ────────────────────────────────────────────────────

async def print_streamed_response(stream_generator):
    print(f"\n{Colors.INFO}Thinking{Colors.RESET}", end="", flush=True)

    try:
        text = ""
        async for chunk in stream_generator:
            print(chunk, end="", flush=True)
            text += chunk
        print('\n', flush=True)
        print_row(
            ('', '', f'({agent.get_message_count()}) message/s in history'),
            colors=[Colors.RESET, Colors.RESET, Colors.INFO],
            column_sizes=[0, 7, 0],
        )
        print_success(f"Response complete ({len(text)} chars)")

    except KeyboardInterrupt:
        print_warning('\n\n[Interrupted]\n', '')
    except Exception as e:
        print_error(f"Response error: {e}")


async def handle_special_commands(user_input: str) -> bool:
    if not user_input.startswith("/"):
        return False

    cmd = user_input[1:].strip().lower()

    if cmd == "models":
        print_model_list()
        return True
    elif cmd == "modelinfo":
        print_model_info()
        return True
    elif cmd.startswith("switch "):
        key = cmd[7:].strip()
        try:
            agent.switch_model(key)
            print_success(f"Switched to {key}")
            print_model_info()
        except ValueError as e:
            print_error(str(e))
            print_model_list()
        return True
    elif cmd in ("help", "?"):
        print_section_header("Commands", Colors.PRIMARY)
        for line in [
            ("/models", "List models"),
            ("/switch <key>", "Switch model"),
            ("/modelinfo", "Current model info"),
            ("/clear", "Clear history"),
            ("/help", "This help"),
            ("exit / quit", "Quit"),
        ]:
            print_tuble(line, Colors.PRIMARY, Colors.RESET, spacing="18")
        return True
    elif cmd == "clear":
        agent.clear_messages()
        print_success("History cleared")
        return True

    return False


def handle_args(args):
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


def create_prompt_session():
    bindings = KeyBindings()

    @bindings.add("c-j")
    def _(event):
        event.current_buffer.validate_and_handle()

    return PromptSession(
        completer=FileCompleter(),
        history=FileHistory(".copane-history"),
        complete_while_typing=True,
        mouse_support=True,
        multiline=True,
        prompt_continuation=lambda width, line_number, is_soft_wrap: ansi_bold(
            f"{line_number} {CONTINUATION_PROMPT} ", CONTINUATION_COLOR),
        key_bindings=bindings,
    )

# ── Main loop ────────────────────────────────────────────────────────────


async def main():
    args = parse_args()

    # Load environment file first (before any module-level code depends on it)
    load_env_file(args.env_file)

    if handle_args(args):
        return

    if args.no_banner:
        print_no_banner()
    else:
        print_banner()

    session = create_prompt_session()

    print("\033[s__COPANE_READY__\033[u", file=sys.stderr,
          flush=True)  # Sentinel for external tools

    initial = build_initial_query(args)
    if initial:
        await print_streamed_response(agent.stream_response(initial))
        print_section_header(f"{STAR} Interactive Mode", Colors.SUCCESS)
        print("Continue chatting or type 'exit'.\n")

    while True:
        try:
            user_input = await session.prompt_async(PROMPT_SYMBOL)

            if user_input.strip().lower() in EXIT_COMMANDS:
                print(EXIT_MESSAGE)
                break

            if not user_input:
                continue

            if await handle_special_commands(user_input):
                print_dim(SEPARATOR)
                continue

            expanded = expand_files(user_input)
            print_dim('[Processing…]')

            await print_streamed_response(agent.stream_response(expanded))
            print_dim(f'{SEPARATOR}\n')

        except KeyboardInterrupt:
            print_warning('\n\n[Interrupted]\n', '')
            try:
                confirm = await session.prompt_async(
                    ansi_warn('Exit? (y/N): ', '')
                )
                if confirm.strip().lower() in ("y", "yes"):
                    print_success("Goodbye!", '')
                    break
                print_info(f"Continuing…\n", '')
            except KeyboardInterrupt:
                print_success(f"\nGoodbye!", '')
                break
        except Exception as e:
            print_error(f"Unexpected error: {e}")
            print_info("Continuing…\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Colors.SUCCESS}Goodbye!{Colors.RESET}")
    except Exception as e:
        print_error(f"Fatal error: {e}")
        sys.exit(1)
