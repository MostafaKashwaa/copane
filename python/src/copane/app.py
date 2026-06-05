#!/usr/bin/env python3
"""
copane — AI Coding Agent for Vim + Tmux
Multi-model, file-aware, terminal-first.
"""

import os
import asyncio
import sys
import logging
import subprocess
import textwrap
from pathlib import Path

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
from copane import session_store


COPANE_HISTORY = os.path.expanduser('~/.local/share/copane/.copane_history')
os.makedirs(os.path.dirname(COPANE_HISTORY), exist_ok=True)

# ── Mutable renderer state ─────────────────────────────────────────────
# Set once during startup, then /renderer can swap it at runtime.

_current_renderer: Renderer | None = None


# ── Path to view_conversation.py ───────────────────────────────────────

def _view_conversation_script() -> Path:
    """Return the path to view_conversation.py, relative to the copane package."""
    import copane
    # return Path(copane.__file__).parent.parent.parent / "view_conversation.py"
    return Path(copane.__file__).parent / "view_conversation.py"


# ── Formatting helpers ─────────────────────────────────────────────────

def _fmt_tokens(n: int) -> str:
    """Format a token count for display (e.g. 1234 → '1.2k')."""
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


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


# ── Session list display ───────────────────────────────────────────────

def _print_sessions_list(agent):
    """Print all sessions from the manifest, highlighting the current one."""
    manifest = session_store.load_manifest()
    if not manifest:
        print_info("No saved sessions.\n", Colors.DIM)
        return

    print_section_header("Saved Sessions", Colors.PRIMARY)
    current_id = agent.session_id

    for entry in manifest[:20]:  # show last 20
        sid = entry.get("session_id", "?")
        is_current = sid == current_id
        marker = "→ " if is_current else "  "

        title = entry.get("title") or ""
        if title:
            title_display = f" — {title}"
        else:
            first = entry.get("first_user_message", "")
            title_display = f" — {first[:60]}" if first else ""

        turns = entry.get("turn_count", 0)
        inp = entry.get("input_tokens", 0)
        out = entry.get("output_tokens", 0)
        model = entry.get("model", "?").split("/")[-1]  # just the model name
        updated = entry.get("last_updated", "")[:16]  # date part

        # Token string: only show if we have real data
        if inp or out:
            tok_str = f"  ⬇{_fmt_tokens(inp)} ⬆{_fmt_tokens(out)}"
        else:
            tok_str = ""

        color = Colors.SUCCESS if is_current else Colors.RESET
        desc_color = Colors.INFO if is_current else Colors.DIM

        print_tuble(
            (f"{marker}{sid[:16]}", f"{updated}  {model}  turns:{turns}{tok_str}{title_display}"),
            color, desc_color, spacing="20",
        )
    print()  # blank line after list


def _print_session_view(session_id: str):
    """Display a session using view_conversation.py --pager.

    Shells out to the standalone viewer script, which renders the
    conversation with Rich panels / markdown in an interactive pager.
    Falls back to a plain-text warning if the script isn't found.
    """
    script = _view_conversation_script()
    session_file = session_store.session_file_path(session_id)

    if not script.exists():
        print_error(
            f"view_conversation.py not found at {script}. "
            "Installation may be incomplete."
        )
        return

    if not session_file.exists():
        # Fall back to legacy .json (pre-jsonl sessions).
        # The viewer script handles all formats — no migration needed.
        legacy = session_store.legacy_session_path(session_id)
        if legacy.exists():
            session_file = legacy
        else:
            print_error(f"Session file not found: {session_id}")
            return

    # Show a brief header before handing off to the pager
    manifest = session_store.load_manifest()
    for entry in manifest:
        if entry.get("session_id") == session_id:
            title = entry.get("title") or entry.get("first_user_message", "")[:60]
            model = entry.get("model", "?")
            turns = entry.get("turn_count", 0)
            inp = entry.get("input_tokens", 0)
            out = entry.get("output_tokens", 0)

            print_section_header(f"Session: {title}", Colors.ACCENT)
            print_tuble(("Model:", model), Colors.PRIMARY, Colors.RESET, spacing="20")
            print_tuble(("Turns:", str(turns)), Colors.PRIMARY, Colors.RESET, spacing="20")
            if inp or out:
                print_tuble(
                    ("Tokens:", f"⬇{_fmt_tokens(inp)} input  ⬆{_fmt_tokens(out)} output"),
                    Colors.PRIMARY, Colors.RESET, spacing="20",
                )
            print()
            break

    try:
        subprocess.run(
            [sys.executable, str(script), str(session_file), "--pager"],
            check=False,
        )
    except FileNotFoundError:
        print_error("Python interpreter not found. Cannot launch viewer.")
    except Exception as e:
        print_error(f"Failed to launch viewer: {e}")


# ── Special command dispatch ───────────────────────────────────────────

async def handle_special_commands(user_input: str) -> bool:
    """Handle in-REPL slash commands like /models, /switch, /clear, /renderer.

    Returns True if the input was consumed as a command.
    """
    agent = get_agent()
    if not user_input.startswith("/"):
        return False

    cmd = user_input[1:].strip()

    # Keep original case for /rename title (args may have spaces/case)
    cmd_lower = cmd.lower()

    # ── /models ─────────────────────────────────────────────────────
    if cmd_lower == "models":
        from copane.cli import print_model_list
        print_model_list()
        return True

    # ── /modelinfo ──────────────────────────────────────────────────
    if cmd_lower == "modelinfo":
        from copane.cli import print_model_info
        print_model_info()
        return True

    # ── /switch <key> ───────────────────────────────────────────────
    if cmd_lower.startswith("switch "):
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

    # ── /renderer [key] ─────────────────────────────────────────────
    if cmd_lower.startswith("renderer"):
        global _current_renderer
        parts = cmd.split(maxsplit=1)
        key = parts[1].strip() if len(parts) > 1 else ""

        if key == "":
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
                print_info("Available renderers:", Colors.DIM)
                for rkey, rdesc in sorted(AVAILABLE_RENDERERS.items()):
                    print_tuble(
                        (f"  {rkey}", rdesc),
                        Colors.PRIMARY, Colors.DIM, spacing="20",
                    )
        return True

    # ── /sessions ───────────────────────────────────────────────────
    if cmd_lower == "sessions":
        _print_sessions_list(agent)
        return True

    # ── /view <session_id> ──────────────────────────────────────────
    if cmd_lower.startswith("view "):
        sid = cmd[5:].strip()
        if not sid:
            print_error("Usage: /view <session_id>")
            return True
        # Support partial-id matching: try exact first, then prefix
        manifest = session_store.load_manifest()
        matched = None
        for entry in manifest:
            eid = entry.get("session_id", "")
            if eid == sid:
                matched = eid
                break
            if eid.startswith(sid) and matched is None:
                matched = eid
        if matched is None:
            print_error(f"Session '{sid}' not found. Use /sessions to list.")
            return True
        _print_session_view(matched)
        return True

    # ── /resume <session_id> ────────────────────────────────────────
    if cmd_lower.startswith("resume "):
        sid = cmd[7:].strip()
        if not sid:
            print_error("Usage: /resume <session_id>")
            return True
        # Partial-id matching
        manifest = session_store.load_manifest()
        matched = None
        for entry in manifest:
            eid = entry.get("session_id", "")
            if eid == sid:
                matched = eid
                break
            if eid.startswith(sid) and matched is None:
                matched = eid
        if matched is None:
            print_error(f"Session '{sid}' not found. Use /sessions to list.")
            return True
        if not agent.resume_session(matched):
            print_error(f"Failed to load session '{matched}'.")
            return True
        # Show what we loaded
        title = ""
        inp = 0
        out = 0
        for entry in manifest:
            if entry.get("session_id") == matched:
                title = entry.get("title") or entry.get("first_user_message", "")
                inp = entry.get("input_tokens", 0)
                out = entry.get("output_tokens", 0)
                break
        print_success(f"Resumed: {title[:80]}")
        print_info(f"  {matched}", Colors.DIM)
        print_info(f"  {agent.get_message_count()} turns loaded", Colors.DIM)
        if inp or out:
            print_info(f"  ⬇{_fmt_tokens(inp)} input  ⬆{_fmt_tokens(out)} output", Colors.DIM)
        return True

    # ── /delete <session_id> ────────────────────────────────────────
    if cmd_lower.startswith("delete "):
        sid = cmd[7:].strip()
        if not sid:
            print_error("Usage: /delete <session_id>")
            return True
        # Partial-id matching
        manifest = session_store.load_manifest()
        matched = None
        for entry in manifest:
            eid = entry.get("session_id", "")
            if eid == sid:
                matched = eid
                break
            if eid.startswith(sid) and matched is None:
                matched = eid
        if matched is None:
            print_error(f"Session '{sid}' not found. Use /sessions to list.")
            return True
        if matched == agent.session_id:
            print_warning("Cannot delete the active session. /clear or switch first.")
            return True
        session_store.remove_manifest_entry(matched)
        print_success(f"Deleted session: {matched}")
        return True

    # ── /rename <session_id> <new_title> ────────────────────────────
    if cmd_lower.startswith("rename "):
        args_str = cmd[7:].strip()  # preserve case for title
        parts = args_str.split(maxsplit=1)
        if len(parts) < 2:
            print_error("Usage: /rename <session_id> <new_title>")
            return True
        sid_part, new_title = parts
        # Partial-id matching
        manifest = session_store.load_manifest()
        matched = None
        for entry in manifest:
            eid = entry.get("session_id", "")
            if eid == sid_part:
                matched = eid
                break
            if eid.startswith(sid_part) and matched is None:
                matched = eid
        if matched is None:
            print_error(f"Session '{sid_part}' not found. Use /sessions to list.")
            return True
        if session_store.rename_session_title(matched, new_title):
            print_success(f"Renamed to: {new_title}")
        else:
            print_error(f"Failed to rename session '{matched}'.")
        return True

    # ── /help ───────────────────────────────────────────────────────
    if cmd_lower in ("help", "?"):
        current_key = get_renderer_key(_current_renderer)
        rdesc = AVAILABLE_RENDERERS.get(current_key, "unknown")
        print_section_header("Commands", Colors.PRIMARY)
        for line in [
            ("/models", "List models"),
            ("/switch <key>", "Switch model"),
            ("/renderer [key]", "List or switch renderers"),
            ("/modelinfo", "Current model info"),
            ("/sessions", "List saved sessions"),
            ("/resume <id>", "Resume a saved session"),
            ("/view <id>", "View a session in rich pager"),
            ("/rename <id> <title>", "Rename a session"),
            ("/delete <id>", "Delete a session"),
            ("/clear", "Clear history (saves first)"),
            ("/help", "This help"),
            ("exit / quit", "Quit"),
        ]:
            print_tuble(line, Colors.PRIMARY, Colors.RESET, spacing="20")
        print_tuble(
            ("Renderer:", f"{current_key} — {rdesc}"),
            Colors.PRIMARY, Colors.INFO, spacing="20",
        )
        return True

    # ── /clear ──────────────────────────────────────────────────────
    if cmd_lower == "clear":
        agent.save_current_session()
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

    # ── Migrate old ~/.copane/logs/ → sessions (one-time, idempotent) ──
    session_store.migrate_logs_to_sessions()

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
                agent.save_current_session()
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
                    agent.save_current_session()
                    print_success("Goodbye!", "")
                    break
                print_info("Continuing…\n", "")
            except KeyboardInterrupt:
                agent.save_current_session()
                print_success("\nGoodbye!", "")
                break
        except Exception as e:
            print_error(f"Unexpected error: {e}")
            print_info("Continuing…\n")


def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        # Ctrl-C at the top level (e.g. during initial --mode query)
        try:
            get_agent().save_current_session()
        except Exception:
            pass
        print(f"\n{Colors.SUCCESS}Goodbye!{Colors.RESET}")
    except Exception as e:
        print_error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
