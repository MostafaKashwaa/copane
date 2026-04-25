#!/usr/bin/env python3
"""
copane — AI Coding Agent for Vim + Tmux
Multi-model, file-aware, terminal-first.
"""

import os
import asyncio
import argparse
from re import T
import sys
from datetime import datetime

from prompt_toolkit import ANSI, PromptSession
from prompt_toolkit.history import FileHistory
from dotenv import load_dotenv
from prompt_toolkit.key_binding.key_bindings import KeyBindings
from copane.tmux_agent import agent
from copane.term_styles import (
    Colors,
    LOGO,
    LOGO_COMPACT,
    LOGO_ONELINER,
    print_success,
    print_error,
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

# Wrap the raw logo with colour
LOGO_DISPLAY = f"""
{Colors.PRIMARY}{Colors.BOLD}{LOGO}{Colors.RESET}"""


def print_banner():
    """Professional startup banner with system info."""
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    print("\033[2J\033[H", end="")

    print(LOGO_DISPLAY)

    print(f"{Colors.SECONDARY}{DOUBLE_SEPARATOR}{Colors.RESET}")
    print(f"  {Colors.INFO}{Colors.BOLD}Version:{Colors.RESET}  {APP_VERSION}")
    print(f"  {Colors.INFO}{Colors.BOLD}Date:{Colors.RESET}    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  {Colors.INFO}{Colors.BOLD}Python:{Colors.RESET}  {sys.version.split()[0]}")
    print(f"  {Colors.INFO}{Colors.BOLD}Terminal:{Colors.RESET} {os.getenv('TERM', 'unknown')}")
    print(f"{Colors.SECONDARY}{DOUBLE_SEPARATOR}{Colors.RESET}")

    # Model and API status
    print(f"\n{Colors.BOLD}Status:{Colors.RESET}")

    model_info = agent.get_model_info()
    model_color = Colors.SUCCESS if model_info["status"] in ["configured", "available"] else Colors.WARNING
    print(f"  {BULLET} Model:  {model_color}{Colors.BOLD}{model_info['description']}{Colors.RESET}")
    print(f"           {Colors.INFO}{model_info['type']}{Colors.RESET} · "
          f"{model_color}{model_info['status']}{Colors.RESET}")

    api_parts = []
    if deepseek_key:
        api_parts.append(f"{Colors.SUCCESS}✓ DeepSeek{Colors.RESET}")
    else:
        api_parts.append(f"{Colors.WARNING}⚠ DeepSeek{Colors.RESET}")
    if OPENAI_API_KEY:
        api_parts.append(f"{Colors.SUCCESS}✓ OpenAI{Colors.RESET}")
    else:
        api_parts.append(f"{Colors.WARNING}⚠ OpenAI{Colors.RESET}")
    print(f"  {BULLET} APIs:   {' | '.join(api_parts)}")

    cwd = os.getcwd()
    if len(cwd) > 50:
        cwd = "…" + cwd[-48:]
    print(f"  {BULLET} Dir:    {Colors.ACCENT}{cwd}{Colors.RESET}")

    # Quick commands
    print(f"\n{Colors.BOLD}Commands:{Colors.RESET}")
    print(f"  {Colors.PRIMARY}@file{Colors.RESET}         Include file content")
    print(f"  {Colors.PRIMARY}/models{Colors.RESET}       List models")
    print(f"  {Colors.PRIMARY}/switch <key>{Colors.RESET}  Switch model")
    print(f"  {Colors.PRIMARY}exit{Colors.RESET}          Quit")
    print(f"  {Colors.PRIMARY}Ctrl-C{Colors.RESET}        Cancel")
    print(f"  {Colors.PRIMARY}Tab{Colors.RESET}           Auto-complete file")

    print(f"\n{Colors.SECONDARY}{DOUBLE_SEPARATOR}{Colors.RESET}")
    print(f"{Colors.SUCCESS}{Colors.BOLD}{STAR} {APP_NAME} ready. Ask away:{Colors.RESET}\n")


# ── Argument parser ──────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description=f"{Colors.BOLD}{APP_NAME} — {APP_TAGLINE}{Colors.RESET}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
{Colors.ACCENT}Examples:{Colors.RESET}
  {Colors.PRIMARY}{APP_NAME}{Colors.RESET}                               Interactive mode
  {Colors.PRIMARY}{APP_NAME} --mode explain --file main.py{Colors.RESET}
  {Colors.PRIMARY}{APP_NAME} --mode test --text "def add(a,b): return a+b"{Colors.RESET}
  {Colors.PRIMARY}{APP_NAME} --list-models{Colors.RESET}
  {Colors.PRIMARY}{APP_NAME} --switch deepseek-chat{Colors.RESET}
  {Colors.PRIMARY}{APP_NAME} --model-info{Colors.RESET}
        """,
    )

    parser.add_argument("--mode", choices=["explain", "test", "review", "refactor"],
                        help="Quick action mode")
    parser.add_argument("--file", help="File to operate on (used with --mode)")
    parser.add_argument("--text", help="Direct text to operate on (overrides --file)")
    parser.add_argument("--no-banner", action="store_true", help="Skip the banner")
    parser.add_argument("--list-models", action="store_true", help="List models and exit")
    parser.add_argument("--switch", help="Switch to a different model and exit")
    parser.add_argument("--model-info", action="store_true", help="Show model info and exit")
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

    header = f"{'':3}{'Key':<20} {'Name':<20} {'Type':<10} {'Status':<15} Description"
    print(f"{Colors.BOLD}{header}{Colors.RESET}")
    print(f"{Colors.SECONDARY}{SEPARATOR}{Colors.RESET}")

    for key, info in models.items():
        sc = (Colors.SUCCESS if info["status"] == "configured"
              else Colors.INFO if info["status"] == "available"
              else Colors.WARNING if info["status"] == "missing_api_key"
              else Colors.ERROR)
        sel = f"{Colors.SUCCESS}{ARROW_RIGHT}{Colors.RESET}" if info["is_selected"] else "  "
        print(f"{sel} {Colors.BOLD}{key:<20}{Colors.RESET} {info['name']:<20} {info['type']:<10} "
              f"{sc}{info['status']:<15}{Colors.RESET} {info['description']}")

    print(f"\n{Colors.INFO}Use /switch <model_key> to change.{Colors.RESET}")


def print_model_info():
    mi = agent.get_model_info()
    sc = Colors.SUCCESS if mi["status"] in ("configured", "available") else Colors.WARNING
    print_section_header(f"{STAR} Current Model", Colors.ACCENT)
    print(f"  {Colors.BOLD}Key:{Colors.RESET}         {mi['key']}")
    print(f"  {Colors.BOLD}Name:{Colors.RESET}        {mi['name']}")
    print(f"  {Colors.BOLD}Description:{Colors.RESET}  {mi['description']}")
    print(f"  {Colors.BOLD}Type:{Colors.RESET}        {mi['type']}")
    print(f"  {Colors.BOLD}Base URL:{Colors.RESET}    {mi['base_url']}")
    print(f"  {Colors.BOLD}Status:{Colors.RESET}      {sc}{mi['status']}{Colors.RESET}")
    if mi["env_key"]:
        print(f"  {Colors.BOLD}Env Key:{Colors.RESET}    {mi['env_key']}")
        ak = os.getenv(mi["env_key"])
        if ak:
            mk = ak[:4] + "…" + ak[-4:] if len(ak) > 8 else "***"
            print(f"  {Colors.BOLD}API Key:{Colors.RESET}    {Colors.SUCCESS}{mk}{Colors.RESET}")
        else:
            print(f"  {Colors.BOLD}API Key:{Colors.RESET}    {Colors.WARNING}Not set{Colors.RESET}")


# ── Streaming helpers ────────────────────────────────────────────────────

async def print_streamed_response(stream_generator):
    print(f"\n{Colors.INFO}Thinking{Colors.RESET}", end="", flush=True)

    try:
        text = ""
        async for chunk in stream_generator:
            print(chunk, end="", flush=True)
            text += chunk
        print()
        print_success(f"Response complete ({len(text)} chars)")
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}\n[Interrupted]{Colors.RESET}\n")
    except Exception as e:
        print_error(f"Response error: {e}")


async def handle_special_commands(user_input: str, session: PromptSession) -> bool:
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
            print(f"  {Colors.PRIMARY}{line[0]:<18}{Colors.RESET} {line[1]}")
        return True
    elif cmd == "clear":
        agent.clear_messages()
        print_success("History cleared")
        return True

    return False


# ── Main loop ────────────────────────────────────────────────────────────

async def main():
    args = parse_args()

    # Load environment file first (before any module-level code depends on it)
    load_env_file(args.env_file)

    if args.list_models:
        print_model_list()
        return
    if args.switch:
        try:
            agent.switch_model(args.switch)
            print_success(f"Switched to {args.switch}")
            print_model_info()
        except ValueError as e:
            print_error(str(e))
            print_model_list()
        return
    if args.model_info:
        print_model_info()
        return

    if not args.no_banner:
        print_banner()
    else:
        print(f"{Colors.PRIMARY}{Colors.BOLD}{APP_NAME} (no-banner mode){Colors.RESET}\n")

    bindings = KeyBindings()
    @bindings.add("c-j")
    def _(event):
        event.current_buffer.validate_and_handle()

    session = PromptSession(
        completer=FileCompleter(),
        history=FileHistory(".copane-history"),
        complete_while_typing=True,
        mouse_support=True,
        multiline=True,
        prompt_continuation=lambda width, line_number, is_soft_wrap: ANSI(f"{Colors.PRIMARY}{Colors.BOLD}{line_number} {ARROW_RIGHT} {Colors.RESET}"),
        key_bindings=bindings,
    )

    initial = build_initial_query(args)
    if initial:
        await print_streamed_response(agent.stream_response(initial))
        print_section_header(f"{STAR} Interactive Mode", Colors.SUCCESS)
        print("Continue chatting or type 'exit'.\n")

    print("\033[s__COPANE_READY__\033[u", file=sys.stderr, flush=True)  # Sentinel for external tools

    while True:
        try:
            user_input = await session.prompt_async(
                ANSI(f"{Colors.PRIMARY}{Colors.BOLD}{ARROW_RIGHT}{ARROW_RIGHT}{ARROW_RIGHT} {Colors.RESET}")
            )

            if user_input.strip().lower() in ("exit", "quit", "q"):
                print(f"\n{Colors.SUCCESS}{STAR} {APP_NAME} — goodbye!{Colors.RESET}")
                break

            if not user_input:
                continue

            if await handle_special_commands(user_input, session):
                print(f"\n{Colors.DIM}{SEPARATOR}{Colors.RESET}\n")
                continue

            expanded = expand_files(user_input)
            print(f"{Colors.DIM}[Processing…]{Colors.RESET}")
            await print_streamed_response(agent.stream_response(expanded))
            print(f"\n{Colors.DIM}{SEPARATOR}{Colors.RESET}\n")

        except KeyboardInterrupt:
            print(f"\n{Colors.WARNING}\n[Interrupted]{Colors.RESET}\n")
            try:
                confirm = await session.prompt_async(
                    ANSI(f"{Colors.WARNING}Exit? (y/N): {Colors.RESET}")
                )
                if confirm.strip().lower() in ("y", "yes"):
                    print(f"{Colors.SUCCESS}Goodbye!{Colors.RESET}")
                    break
                print(f"{Colors.INFO}Continuing…{Colors.RESET}\n")
            except KeyboardInterrupt:
                print(f"\n{Colors.SUCCESS}Goodbye!{Colors.RESET}")
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
