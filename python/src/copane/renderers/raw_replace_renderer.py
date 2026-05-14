"""
RawReplaceRenderer — stream responsive, replace spans in-place.

Writes the trailing incomplete line as *directly formatted* text,
re-rendering it in-place (``\\r`` + formatted + ``\\033[K``) on
every chunk.  Incomplete markdown spans (e.g. ``**bo``) are left
as raw text by ``format_inline()``, so the user naturally sees
markers appear then "resolve" into ANSI styling once the closing
marker arrives — without ever writing duplicate text.

Complete lines are emitted already-formatted.  Code fences,
blockquotes, and tables accumulate raw lines during streaming
and are redrawn with styling on close via cursor-up-and-redraw.

Uses ``copane.screen_utils`` for cursor escapes, measurement, and
composable block-level operations (``overwrite_block``,
``rerender_in_place``).

Block dispatch is handled by a pluggable state machine
(``_state_machine.py``).  Adding a new block type means writing a
new ``State`` subclass and wiring it into ``NormalState`` — no
changes to the renderer's dispatch loop.
"""

from __future__ import annotations

import re
import shutil
import sys

from copane import screen_utils
from copane.renderers._base import Renderer
from copane.renderers._state_machine import (
    FenceState,
    LineResult,
    NormalState,
    State,
)
from copane.term_styles import Colors
from copane.renderers._inline_formatting import format_inline, _DIM, _RESET


class RawReplaceRenderer(Renderer):
    """Stream markdown with in-place span resolution.

    *   **Trailing incomplete line** — kept on the current terminal
        line; re-rendered with ``\\r`` + ANSI + ``\\033[K`` on every
        chunk so the user sees markers appear then "resolve" into
        formatted text in-place.
    *   **Complete normal lines** — written once, directly formatted
        (the trailing text is overwritten with ``\\r`` first).
    *   **Fenced code blocks** — raw lines stream through; redrawn
        with box borders on close via cursor-up.
    *   **Blockquotes** — same accumulate-then-redraw.
    *   **Tables** — pipe-detected rows accumulate raw until a
        non-table line appears, then redrawn with aligned columns
        and Unicode box borders.
    """

    def __init__(self) -> None:
        self._line_buf: str = ""
        self._last_formatted: str = ""
        self._term_width: int = 80
        self._trailing_lines: int = 0  # screen rows occupied by the trailing text
        self._state: State = NormalState(self)
        self._in_thinking: bool = False

    # ── Lifecycle ───────────────────────────────────────────────────

    def on_response_begin(self) -> None:
        self._line_buf = ""
        self._last_formatted = ""
        self._term_width = shutil.get_terminal_size().columns
        self._trailing_lines = 0
        self._state = NormalState(self)
        self._in_thinking = False

    def on_response_complete(self) -> None:
        self._in_thinking = False

        # Flush any open block state (fence, blockquote, table)
        result = self._state.flush(self._term_width)
        if result is not None:
            self._apply_result(result)

        if self._line_buf:
            self._cursor_up_trailing()
            formatted = format_inline(self._line_buf)
            sys.stdout.write(screen_utils.write_line(formatted))
            sys.stdout.flush()
            self._line_buf = ""
            self._last_formatted = ""
            self._trailing_lines = 0

        print()

    # ── Chunk handlers ──────────────────────────────────────────────

    def on_thinking_chunk(self, chunk: str) -> None:
        if not self._in_thinking:
            self._in_thinking = True
        sys.stdout.write(f"{_DIM}{chunk}{_RESET}")
        sys.stdout.flush()

    def on_text_chunk(self, chunk: str) -> None:
        if not chunk:
            return

        if self._in_thinking:
            sys.stdout.write('\n')
            sys.stdout.flush()
            self._in_thinking = False
            self._line_buf = ""
            self._last_formatted = ""

        self._line_buf += chunk

        # Drain complete lines
        while "\n" in self._line_buf:
            raw_line, self._line_buf = self._line_buf.split("\n", 1)
            self._emit_complete_line(raw_line)

        # Re-render the trailing incomplete line in-place
        if self._line_buf:
            self._rerender_trailing()

    # ── Cursor helpers ──────────────────────────────────────────────

    def _cursor_up_trailing(self) -> None:
        """Move the cursor up to the first screen row of the trailing
        text.  Assumes the cursor is currently on the *last* row of
        that text (where ``_rerender_trailing`` left it)."""
        if self._trailing_lines > 1:
            sys.stdout.write(screen_utils.cursor_up(self._trailing_lines - 1))
            sys.stdout.flush()

    def _write_clear(self, text: str) -> None:
        """Write *text* from column 0 and clear the rest of the line."""
        sys.stdout.write(
            f"{screen_utils.cursor_col0()}{text}{screen_utils.clear_to_eol()}"
        )

    def _emit_line(self, text: str) -> None:
        """Write *text* from column 0, clear remainder, advance to
        the next terminal row."""
        self._write_clear(text)
        sys.stdout.write("\n")
        sys.stdout.flush()
        self._trailing_lines = 0

    # ── State transition ───────────────────────────────────────────

    def set_state(self, new_state: State) -> None:
        self._state = new_state

    # ── Result dispatch ────────────────────────────────────────────

    def _apply_result(self, result: LineResult) -> None:
        """Execute the I/O actions described by a ``LineResult``,
        then re-dispatch ``replay_line`` if set."""
        if result.body:
            self._emit_line(result.body)

        if result.redraw_target is not None:
            sys.stdout.write(
                screen_utils.overwrite_block(
                    result.previous_screen_rows,
                    result.redraw_target,
                    self._term_width,
                )
            )
            sys.stdout.flush()

        if result.replay_line is not None:
            self._emit_complete_line(result.replay_line)

    def _emit_complete_line(self, raw_line: str) -> None:
        """Finalize a complete line (a ``\\n`` just arrived).

        The trailing formatted text from the previous
        ``_rerender_trailing()`` call may span multiple terminal
        rows, so we move the cursor up first, then dispatch to
        the current state machine.
        """
        self._cursor_up_trailing()
        result = self._state.handle_line(raw_line, self._term_width)
        self._apply_result(result)

    # ── Trailing line re-render ────────────────────────────────────

    def _rerender_trailing(self) -> None:
        """Re-render the trailing incomplete line in-place.

        Moves the cursor up to the first screen row of the trailing
        text (which may wrap across multiple rows), then writes the
        new formatted text from column 0 and clears any leftover
        lines if the text shrank.  ``format_inline()`` naturally
        leaves incomplete spans as raw markers, which provides the
        "markers appear then resolve" effect without ever
        duplicating text.
        """
        if isinstance(self._state, FenceState):
            return

        formatted = format_inline(self._line_buf)
        if formatted == self._last_formatted:
            return

        # Move cursor to the first screen row of the previous trailing text
        self._cursor_up_trailing()

        # Write the new formatted text from column 0, clearing the rest of the line
        self._write_clear(formatted)

        # If the new text is shorter (fewer screen rows), clear the leftover lines
        new_lines = screen_utils.screen_lines(formatted, self._term_width)
        old_lines = self._trailing_lines
        if new_lines < old_lines:
            diff = old_lines - new_lines
            # We're currently on the first screen line of the new text.
            # Move down to each leftover line and clear it, then move back up.
            for _ in range(diff):
                sys.stdout.write('\n' + screen_utils.clear_to_eol())
            sys.stdout.write(screen_utils.cursor_up(diff))

        sys.stdout.flush()
        self._trailing_lines = new_lines
        self._last_formatted = formatted

