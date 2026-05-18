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
from copane.term_styles import Colors, get_colored
from copane.renderers._inline_formatting import format_inline, _DIM, _RESET
from copane.tools._base import ToolResult


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
        # total screen rows emitted (including tool calls)
        self._consumed_rows: int = 0
        # call_id -> screen row where the tool call was emitted
        self._tool_call_rows: dict[str, int] = {}
        self._tool_call_text: dict[str, str] = {}

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
        self._consumed_rows += screen_utils.screen_lines(chunk, self._term_width)

    def on_text_chunk(self, chunk: str) -> None:
        if not chunk:
            return

        if self._in_thinking:
            sys.stdout.write('\n\r')
            sys.stdout.flush()
            self._consumed_rows += 1
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

    def on_tool_call_chunk(self, chunk: str) -> None:
        if self._in_thinking:
            sys.stdout.write('\n\r')
            sys.stdout.flush()
            self._consumed_rows += 1
            self._in_thinking = False
            self._line_buf = ""
            self._last_formatted = ""


        tool_name, call_id = chunk
        # Flush any trailing incomplete line before printing the tool call, then reset state
        if self._line_buf:
            self._cursor_up_trailing()
            formatted = format_inline(self._line_buf)
            sys.stdout.write(screen_utils.write_line(formatted))
            sys.stdout.flush()
            self._line_buf = ""
            self._last_formatted = ""
            self._consumed_rows += self._trailing_lines
            self._trailing_lines = 0
            self._state = NormalState(self)

        line = get_colored(f'🔧 [{tool_name}]: ', Colors.ACCENT)
        sys.stdout.write(f"\r{line}\033[k")
        sys.stdout.write('\n')
        # screen_utils.write_line(line)
        # screen_utils.write_clear(line)
        # sys.stdout.write('\n')
        sys.stdout.flush()

        # Record where this call sits in the stream so we can overwrite it with the response when it arrives
        call_rows = screen_utils.screen_lines(line, self._term_width)
        self._tool_call_rows[call_id] = self._consumed_rows #  + call_rows 
        self._tool_call_text[call_id] = line
        self._consumed_rows += call_rows

    def on_tool_response_chunk(self, chunk: str) -> None:
        response, call_id = chunk
        call_row = self._tool_call_rows.get(call_id)
        if not call_row:
            # This shouldn't happen, but if it does we can just print the response inline
            sys.stdout.write(f"\n{response}\n")
            sys.stdout.flush()
            self._consumed_rows += screen_utils.screen_lines(response, self._term_width)  + 1
            self.debug_print(f"no matching tool call found for response with call id '{call_id}', printed inline")
            return

        # tool_result = _format_tool_output(response, self._term_width)
        if isinstance(response, ToolResult):
            color = Colors.SUCCESS if response.success else Colors.ERROR
            if response.error:
                result = f"Error: {response.error}"
            else:
                result = response.output.strip()
        else:
            color = Colors.INFO
            result = response.strip()

        original_line = self._tool_call_text[call_id]
        response_rows = self._term_width - len(original_line) + 2
        result = result.splitlines()[0]
        formatted_response = get_colored(result[:response_rows], color)
        final_response = f"{original_line}  {formatted_response}"

        starting_row = self._consumed_rows + self._trailing_lines
        shift = 0
        if call_row > starting_row:
            # If the call row is below the current cursor position, we need to move down first
            shift = call_row - starting_row
            sys.stdout.write(screen_utils.cursor_down(shift))
            sys.stdout.flush()
        else:
            # Move cursor up to the line of the original tool call
            shift = starting_row - call_row
            sys.stdout.write(screen_utils.cursor_up(shift))
            sys.stdout.flush()

        sys.stdout.write(screen_utils.write_clear(final_response))
        sys.stdout.flush()
        # updated_response_rows = response_rows - screen_utils.screen_lines(original_line, self._term_width)
        updated_response_rows = screen_utils.screen_lines(final_response, self._term_width) - screen_utils.screen_lines(original_line, self._term_width)
        self._consumed_rows += updated_response_rows 

        # Return cursor to the position after the trailing line
        sys.stdout.write(screen_utils.cursor_down(shift))
        sys.stdout.flush()

        # Remove the call_id from tracking since it's now resolved
        del self._tool_call_rows[call_id]

    def on_interrupt(self) -> None:
        # Clears rerenderer state without touching the screen. the caller takes over stdout after this call
        self._line_buf += "\n"  # Ensure the current line is treated as complete and cleared
        sys.stdout.flush()
        self._line_buf = ""
        self._last_formatted = ""
        self._trailing_lines = 0
        self._state = NormalState(self)
        self._in_thinking = False


    # ── Print helpers ──────────────────────────────────────────────
    def debug_print(self, message: str) -> None:
        line = get_colored(f"\n[DEBUG] {message}\n", Colors.DIM)
        sys.stdout.write(line)
        sys.stdout.flush()
        self._consumed_rows += screen_utils.screen_lines(line, self._term_width) + 2

    # def _write(self, text: str) -> int:
    #     """Write raw text to stdout, return number of screen rows consumed."""
    #     rows = screen_utils.screen_lines(text, self._term_width) - 1
    #     # if text.endswith('\n'):
    #         # rows += 1
    #     sys.stdout.write(text)
    #     sys.stdout.flush()
    #     self._consumed_rows += rows
    #     return rows

    # def _write_line(self, text: str) -> int:
    #     """Write text followed by a newline, return number of screen rows consumed."""
    #     rows = self._write(f"{text}\n")
    #     # self._consumed_rows += rows
    #     return rows 

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
        line_rows = screen_utils.screen_lines(text, self._term_width) - 1
        sys.stdout.write('\n\r')
        sys.stdout.flush()
        self._consumed_rows += 1 + line_rows 
        # self._write_line(text)
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
            # Update consumed rows: the new block may be taller or shorter than the previous one, so we adjust by the difference
            lines_length = sum([screen_utils.screen_lines(
                line, self._term_width)
                for line in result.redraw_target]
            )

            self._consumed_rows += lines_length - result.previous_screen_rows
            # self._consumed_rows += screen_utils.visual_width(result.redraw_target) - result.previous_screen_rows
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
                sys.stdout.write('\r\n' + screen_utils.clear_to_eol())
            sys.stdout.write(screen_utils.cursor_up(diff))
            self._consumed_rows -= diff # Adjust consumed rows for the cleared lines

        sys.stdout.flush()
        self._trailing_lines = new_lines
        self._last_formatted = formatted
