"""
RichBufferRenderer — buffer + replace renderer powered by rich.

Text and thinking chunks are printed raw during streaming (identical
to RawRenderer), and simultaneously buffered.  On completion, the
raw output area is cleared via ANSI and replaced with a beautifully
formatted version produced by ``rich.Markdown``.

This gives the best of both worlds: instant feedback during the stream
and pixel-perfect markdown rendering afterwards.  The brief flash of
raw text before replacement is the trade-off.

Depends on ``rich`` (optional).
"""

from __future__ import annotations

import sys

from copane.renderers._base import Renderer
from copane.term_styles import Colors, get_dim

_THINKING_HEADER = f"{Colors.INFO}Thinking{Colors.RESET}"

# Lazy import — rich is an optional dependency
try:
    from rich.console import Console
    from rich.markdown import Markdown
    HAS_RICH = True
except ImportError:
    Console = None  # type: ignore
    Markdown = None
    HAS_RICH = False


class RichBufferRenderer(Renderer):
    """Prints raw during stream, replaces with rich on completion."""

    def __init__(self) -> None:
        if HAS_RICH:
            self._console = Console(force_terminal=True, color_system="truecolor")
        else:
            self._console = None
        self._buffer: list[str] = []
        self._line_count = 0
        self._started = False

    # ── Lifecycle ───────────────────────────────────────────────────

    def on_response_begin(self) -> None:
        self._buffer = []
        self._line_count = 0
        self._started = True
        print(f"\n{_THINKING_HEADER}", end="\n", flush=True)
        # Track the "Thinking" header line
        self._line_count = 1

    def on_response_complete(self) -> None:
        self._started = False
        if not HAS_RICH or not self._console:
            print(flush=True)
            return

        full_text = "".join(self._buffer)
        if not full_text.strip():
            print(flush=True)
            return

        # ── Replace the raw output ──────────────────────────────────
        # Move cursor up past the raw text lines, clear to end of screen,
        # then print the rich-formatted version.
        try:
            sys.stdout.write(f"\033[{self._line_count}F\033[J")
            sys.stdout.flush()
            md = Markdown(full_text, code_theme="monokai")
            self._console.print(md)
        except Exception:
            # If anything goes wrong (e.g. rich markup error in raw text
            # that somehow leaks through), fall back gracefully.
            # The raw text is already there, so just print a newline.
            print()

    # ── Chunks ──────────────────────────────────────────────────────

    def on_thinking_chunk(self, chunk: str) -> None:
        print(get_dim(chunk), end="", flush=True)
        self._line_count += chunk.count("\n")

    def on_text_chunk(self, chunk: str) -> None:
        print(chunk, end="", flush=True)
        self._buffer.append(chunk)
        self._line_count += chunk.count("\n")

    def on_interrupt(self) -> None:
        ...
