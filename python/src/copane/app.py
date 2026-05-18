#!/usr/bin/env python3
"""
copane — AI Coding Agent for Vim + Tmux
Multi-model, file-aware, terminal-first.
"""

import os
import asyncio
import sys
import logging

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from dotenv import load_dotenv
from prompt_toolkit.key_binding.key_bindings import KeyBindings
from copane.completers import CopaneCompleter 

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
from copane.renderers import get_renderer, get_renderer_key, AVAILABLE_RENDERERS, Renderer
from copane.term_styles import (
    COPANE_STYLE_SOLARIZED,
    ansi_bold,
    Colors,
    ansi_warn,
    get_colored,
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
    COPANE_STYLE_MONOKAI,
    COPANE_STYLE_VSCODE,
    COPANE_STYLE_CYAN,
    COPANE_STYLE_LIGHT,
)
from copane.file_utils import FileCompleter, expand_files


COPANE_HISTORY = os.path.expanduser('~/.local/share/copane/.copane_history')
os.makedirs(os.path.dirname(COPANE_HISTORY), exist_ok=True)

# ── Mutable renderer state ─────────────────────────────────────────────
# Set once during startup, then /renderer can swap it at runtime.

_current_renderer: Renderer | None = None


# ── Environment loading ─────────────────────────────────────────────────

def load_env_file(env_path: str | None = None):
    """
    Load the .env file from the given path, or fall back to local .env.

    The path is also stored in COPANE_ENV_FILE so that submodules (e.g.
    tmux_agent) can re-read it if needed.
    """
    default_path = os.path.expanduser("~/.copane.env")
    path = env_path or os.environ.get("COPANE_ENV_FILE") or default_path
    path = os.path.expanduser(path)
    load_dotenv(dotenv_path=path, override=True)
    os.environ.setdefault("COPANE_ENV_FILE", os.path.abspath(path))

    # Silence noisy HTTP-transport loggers so that temporary network
    # blips don't flood the terminal with connection errors.  This is
    # defense-in-depth — copane.tracing already silences langsmith
    # itself, but httpx/httpcore/openai emit their own diagnostics.
    for noisy in ("httpx", "httpcore", "openai._base_client", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


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

    def get_continuation(width, line_number, is_soft_wrap):
        if is_soft_wrap:
            return HTML(f'<style fg="darkgray">{"." * (width - 2)} </style> ')
        else:
            return HTML(f'<style fg="cyan">{line_number + 1} {ARROW_RIGHT}</style> ')

    return PromptSession(
        completer=CopaneCompleter(),
        history=FileHistory(COPANE_HISTORY),
        complete_while_typing=True,
        style=COPANE_STYLE_MONOKAI,
        mouse_support=True,
        multiline=True,
        prompt_continuation=get_continuation,
        key_bindings=bindings,
    )


# ── Special command dispatch ───────────────────────────────────────────

async def handle_special_commands(user_input: str) -> bool:
    """Handle in-REPL slash commands like /models, /switch, /clear, /renderer.

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

    if cmd.startswith("renderer"):
        global _current_renderer
        # Split off the key (may be empty for /renderer with no args)
        parts = cmd.split(maxsplit=1)
        key = parts[1].strip() if len(parts) > 1 else ""

        if key == "":
            # List available renderers, highlighting the current one
            current_key = get_renderer_key(_current_renderer)
            print_section_header("Available Renderers", Colors.PRIMARY)
            for rkey, rdesc in sorted(AVAILABLE_RENDERERS.items()):
                is_current = rkey == current_key
                marker = "→ " if is_current else "  "
                color = Colors.SUCCESS if is_current else Colors.RESET
                desc_color = Colors.INFO if is_current else Colors.DIM
                print_tuble(
                    (f"{marker}{rkey}", rdesc),
                    color, desc_color, spacing="20",
                )
        else:
            try:
                _current_renderer = get_renderer(key)
                rdesc = AVAILABLE_RENDERERS.get(key, "")
                print_success(f"Renderer switched to: {key} — {rdesc}")
            except (ValueError, ImportError) as e:
                print_error(str(e))
                # Show available renderers on error
                print_info("Available renderers:", Colors.DIM)
                for rkey, rdesc in sorted(AVAILABLE_RENDERERS.items()):
                    print_tuble(
                        (f"  {rkey}", rdesc),
                        Colors.PRIMARY, Colors.DIM, spacing="20",
                    )
        return True

    if cmd in ("help", "?"):
        current_key = get_renderer_key(_current_renderer)
        rdesc = AVAILABLE_RENDERERS.get(current_key, "unknown")
        print_section_header("Commands", Colors.PRIMARY)
        for line in [
            ("/models", "List models"),
            ("/switch <key>", "Switch model"),
            ("/renderer [key]", "List or switch renderers"),
            ("/modelinfo", "Current model info"),
            ("/clear", "Clear history"),
            ("/help", "This help"),
            ("exit / quit", "Quit"),
        ]:
            print_tuble(line, Colors.PRIMARY, Colors.RESET, spacing="20")
        print_tuble(
            ("Renderer:", f"{current_key} — {rdesc}"),
            Colors.PRIMARY, Colors.INFO, spacing="20",
        )
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

async def async_main():
    global _current_renderer

    args = parse_args()

    # Load environment file first (before any module-level code depends on it)
    load_env_file(args.env_file)
    print_info(f"Loaded environment from {os.environ['COPANE_ENV_FILE']}\n", Colors.DIM)
    agent = get_agent()  # Initialize agent after env is loaded

    # ── Renderer selection ─────────────────────────────────────────────
    _current_renderer = get_renderer()  # reads COPANE_RENDERER env var

    if not args.no_banner:
        rkey = get_renderer_key(_current_renderer)
        rdesc = AVAILABLE_RENDERERS.get(rkey, "")
        print_info(f"Renderer: {rkey} — {rdesc}", Colors.DIM)

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
            await print_streamed_response(agent.stream_response(initial), renderer=_current_renderer)
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

            await print_streamed_response(agent.stream_response(expanded), renderer=_current_renderer)
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


def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print(f"\n{Colors.SUCCESS}Goodbye!{Colors.RESET}")
    except Exception as e:
        print_error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
