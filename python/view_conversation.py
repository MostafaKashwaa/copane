#!/usr/bin/env python3
"""
Terminal conversation previewer.

Loads a JSON conversation history file (as produced by
ConversationHistory.save_to_file), extracts user and assistant
messages, and pretty-prints them using the ``rich`` library.

Usage:
    python view_conversation.py <path_to_json>
    python view_conversation.py --pager <path_to_json>   # pipe through less -R
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.style import Style
    from rich.table import Table
    from rich.text import Text
except ImportError as e:
    print(f"Error: rich library is required.  Install with:  pip install rich\n{e}",
          file=sys.stderr)
    sys.exit(1)


# ── Styling constants ─────────────────────────────────────────────────

USER_STYLE = Style(color="bright_blue", bold=True)
ASSISTANT_STYLE = Style(color="bright_green", bold=True)
USER_BORDER = Style(color="bright_blue")
ASSISTANT_BORDER = Style(color="bright_green")
DIM_STYLE = Style(dim=True)


# ── Message extraction ────────────────────────────────────────────────

def load_messages(path: Path) -> tuple[list[dict], int, int]:
    """Load a JSON file containing a list of conversation messages.

    Supports both a top-level list and a dict with a ``"messages"`` key.
    """
    with open(path) as f:
        data = json.load(f)

    if isinstance(data, list):
        return data, 0, 0
    if isinstance(data, dict):
        inp = data.get("input_tokens", 0)
        out = data.get("output_tokens", 0)
        # Check for common wrapper keys
        for key in ("messages", "conversation", "history", "data"):
            if key in data and isinstance(data[key], list):
                return data[key], inp, out
    raise ValueError(
        f"Unrecognised JSON structure in {path}.  Expected a list of "
        "messages or a dict with a 'messages' key."
    )


def filter_conversation(messages: list[dict]) -> list[dict]:
    """Return only user and assistant role messages.

    Skips function_call, function_call_output, reasoning, and other
    internal message types.
    """
    return [m for m in messages if m.get("role") in ("user", "assistant")]


# ── Rendering ─────────────────────────────────────────────────────────

def render_conversation(messages: list[dict], console: Console) -> None:
    """Print the full conversation to *console*."""
    for i, msg in enumerate(messages):
        role = msg.get("role", "unknown")
        content = msg.get("content", "").strip()

        if not content:
            continue

        turn_id = msg.get("_turn_id", "")

        if role == "user":
            title = Text(f"User  (turn {turn_id})", style=USER_STYLE) if turn_id else Text(
                "User", style=USER_STYLE)
            panel = Panel(
                content,
                title=title,
                border_style=USER_BORDER,
                padding=(1, 2),
                subtitle=Text(f"#{i}", style=DIM_STYLE),
            )
            console.print(panel)

        elif role == "assistant":
            title = Text(f"Assistant  (turn {turn_id})", style=ASSISTANT_STYLE) if turn_id else Text(
                "Assistant", style=ASSISTANT_STYLE)
            try:
                md = Markdown(content, code_theme="monokai")
            except Exception:
                md = content  # fallback to plain text

            panel = Panel(
                md,
                title=title,
                border_style=ASSISTANT_BORDER,
                padding=(1, 2),
                subtitle=Text(f"#{i}", style=DIM_STYLE),
            )
            console.print(panel)

        # Blank line between messages (already handled by Panel spacing,
        # but add an extra one for readability)
        console.print()


def show_summary(
    messages: list[dict],
        console: Console,
        input_tokens: int = 0,
        output_tokens: int = 0
) -> None:
    """Print a brief summary table."""
    total = len(messages)
    user_count = sum(1 for m in messages if m.get("role") == "user")
    assistant_count = sum(1 for m in messages if m.get("role") == "assistant")

    table = Table(title="Conversation Summary",
                  style="bold", border_style="dim")
    table.add_column("Metric", style="bold")
    table.add_column("Count")

    table.add_row("Total messages", str(total))
    table.add_row("User messages", str(user_count))
    table.add_row("Assistant messages", str(assistant_count))
    table.add_row("Exchanges (turns)", str(min(user_count, assistant_count)))
    if input_tokens > 0 or output_tokens > 0:
        table.add_row("Input tokens", str(input_tokens))
        table.add_row("Output tokens", str(output_tokens))

    console.print()
    console.print(table)
    console.print()


# ── CLI ───────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview a copane conversation from a JSON file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python view_conversation.py history.json\n"
            "  python view_conversation.py --pager history.json\n"
        ),
    )
    parser.add_argument(
        "file",
        type=str,
        help="Path to the conversation JSON file.",
    )
    parser.add_argument(
        "--pager",
        action="store_true",
        help="Pipe output through 'less -R' for scrolling.",
    )
    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="Skip the summary table at the end.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    path = Path(args.file)
    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        messages, inp_tok, out_tok = load_messages(path)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    conversation = filter_conversation(messages)

    if not conversation:
        print("No user or assistant messages found in the file.", file=sys.stderr)
        sys.exit(1)

    # Build the output string by capturing console prints
    # console = Console(force_terminal=True, color_system="auto")
    console = Console(color_system="auto")

    if args.pager:
        # Capture output into a string and pipe through less -R
        import io
        buf = io.StringIO()
        pager_console = Console(
            file=buf, force_terminal=True, color_system="auto")
        render_conversation(conversation, pager_console)
        if not args.no_summary:
            show_summary(conversation, pager_console,
                         input_tokens=inp_tok, output_tokens=out_tok)

        pager_text = buf.getvalue()
        _pipe_to_less(pager_text, path)
    else:
        render_conversation(conversation, console)
        if not args.no_summary:
            show_summary(conversation, console,
                         input_tokens=inp_tok, output_tokens=out_tok)


def _pipe_to_less(text: str, source: Path) -> None:
    """Pipe *text* through ``less -R`` for interactive scrolling."""
    try:
        proc = subprocess.Popen(
            ["less", "-R", "-I", "+/── .*  \\(turn [0-9]*\\) ──"],
            stdin=subprocess.PIPE,
        )
        proc.communicate(input=text.encode("utf-8"))
    except FileNotFoundError:
        # less not available — fall back to direct print
        sys.stdout.write(text)
        sys.stdout.flush()


if __name__ == "__main__":
    main()
