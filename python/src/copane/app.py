#!/usr/bin/env python3
"""
copane — AI Coding Agent for Vim + Tmux
Multi-model, file-aware, terminal-first.
"""

import os
import asyncio
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from dotenv import load_dotenv
from prompt_toolkit.key_binding.key_bindings import KeyBindings

from copane.cli import (
    APP_NAME,
    parse_args,
    handle_args,
    build_initial_query,
)
from copane.ui import (
    print_banner,
    print_no_banner,
    print_streamed_response,
)
from copane.tmux_agent import get_agent 
from copane.term_styles import (
    ansi_bold,
    Colors,
    ansi_warn,
    get_colored,
    print_bold,
    print_dim,
    print_success,
    print_info,
    print_error,
    print_warning,
    print_tuble,
    print_section_header,
    SEPARATOR,
    STAR,
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


# ── REPL constants ─────────────────────────────────────────────────────

PROMPT_SYMBOL = ansi_bold(f"{3*ARROW_RIGHT} ")
EXIT_MESSAGE = get_colored(f"{STAR} {APP_NAME} — goodbye!", Colors.SUCCESS)
EXIT_COMMANDS = {"exit", "quit", "q"}
CONTINUATION_PROMPT = ARROW_RIGHT
CONTINUATION_COLOR = Colors.DIM


# ── Prompt session factory ─────────────────────────────────────────────

def create_prompt_session() -> PromptSession:
    """Create the interactive prompt session with file completion and key bindings."""
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
            f"{line_number} {CONTINUATION_PROMPT} ", CONTINUATION_COLOR
        ),
        key_bindings=bindings,
    )


# ── Special command dispatch ───────────────────────────────────────────

async def handle_special_commands(user_input: str) -> bool:
    """Handle in-REPL slash commands like /models, /switch, /clear.

    Returns True if the input was consumed as a command.
    """
    agent = get_agent()
    if not user_input.startswith("/"):
        return False

    cmd = user_input[1:].strip().lower()

    if cmd == "models":
        from copane.cli import print_model_list
        print_model_list()
        return True

    if cmd == "modelinfo":
        from copane.cli import print_model_info
        print_model_info()
        return True

    if cmd.startswith("switch "):
        key = cmd[7:].strip()
        try:
            agent.switch_model(key)
            print_success(f"Switched to {key}")
            from copane.cli import print_model_info
            print_model_info()
        except ValueError as e:
            print_error(str(e))
            from copane.cli import print_model_list
            print_model_list()
        return True

    if cmd in ("help", "?"):
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

    if cmd == "clear":
        agent.clear_messages()
        print_success("History cleared")
        return True

    return False


# ── Initial query section header ──────────────────────────────────────

def _show_interactive_header(mode: str):
    """Print the 'Starting <Mode>' header for initial queries."""
    mode_titles = {
        "explain": "Code Explanation",
        "test": "Test Generation",
        "review": "Code Review",
        "refactor": "Code Refactoring",
    }
    title = mode_titles.get(mode, mode.title())
    print_section_header(f"{STAR} Starting {title}", Colors.ACCENT)


# ── Main loop ──────────────────────────────────────────────────────────

async def main():
    args = parse_args()

    # Load environment file first (before any module-level code depends on it)
    load_env_file(args.env_file)
    print_info(f"Loaded environment from {os.environ['COPANE_ENV_FILE']}\n", Colors.DIM)
    agent = get_agent()  # Initialize agent after env is loaded

    if handle_args(args):
        return

    if args.no_banner:
        print_no_banner()
    else:
        print_banner()

    session = create_prompt_session()

    # Sentinel for external tools
    print("\033[s__COPANE_READY__\033[u", file=sys.stderr, flush=True)

    # Handle --mode initial query
    if args.mode:
        _show_interactive_header(args.mode)
        initial = build_initial_query(args)
        if initial:
            await print_streamed_response(agent.stream_response(initial))
            print_section_header(f"{STAR} Interactive Mode", Colors.SUCCESS)
            print("Continue chatting or type 'exit'.\n")

    # ── Interactive REPL ────────────────────────────────────────────────
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
            print_dim("[Processing…]")

            await print_streamed_response(agent.stream_response(expanded))
            print_dim(f"{SEPARATOR}\n")

        except KeyboardInterrupt:
            print_warning("\n\n[Interrupted]\n", "")
            try:
                confirm = await session.prompt_async(ansi_warn("Exit? (y/N): ", ""))
                if confirm.strip().lower() in ("y", "yes"):
                    print_success("Goodbye!", "")
                    break
                print_info("Continuing…\n", "")
            except KeyboardInterrupt:
                print_success("\nGoodbye!", "")
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
