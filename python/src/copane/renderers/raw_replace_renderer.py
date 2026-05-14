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

# ── ANSI style fragments ────────────────────────────────────────────────

_BOLD_ON = "\033[1m"
_BOLD_OFF = "\033[22m"
_ITALIC_ON = "\033[3m"
_ITALIC_OFF = "\033[23m"
_STRIKE_ON = "\033[9m"
_STRIKE_OFF = "\033[29m"
_CODE_BG = "\033[48;5;235m"
_CODE_FG = "\033[38;5;51m"
_CODE_OFF = "\033[0m"
_LINK_STYLE = f"{Colors.INFO}{Colors.UNDERLINE}"
_LINK_OFF = Colors.RESET
_DIM = Colors.DIM
_RESET = Colors.RESET

# ── Inline patterns (one capture group for content) ─────────────────────

_BOLD_ITALIC_PAT = re.compile(r"\*\*\*(.+?)\*\*\*")  # ***bold-italic***
_BOLD_PAT = re.compile(r"\*\*(.+?)\*\*")              # **bold**
_ITALIC_PAT = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")  # *italic*
_INLINE_CODE_PAT = re.compile(r"`([^`\n]+?)`")         # `code`
_STRIKE_PAT = re.compile(r"~~(.+?)~~")                 # ~~strikethrough~~
_LINK_PAT = re.compile(r"\[([^\]]+?)\]\([^)]+?\)")     # [text](url)

# Block-level patterns
_HR_PAT = re.compile(r"^[-*_]{3,}\s*$")
_HEADING_PAT = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_UNORDERED_LIST_PAT = re.compile(r"^(\s*)([-*+])\s+(.+)$")
_ORDERED_LIST_PAT = re.compile(r"^(\s*)(\d+\.)\s+(.+)$")

_HEADING_COLORS: dict[int, str] = {
    1: f"{Colors.PRIMARY}{Colors.BOLD}",
    2: f"{Colors.SECONDARY}{Colors.BOLD}",
    3: f"{Colors.ACCENT}{Colors.BOLD}",
    4: f"{Colors.INFO}{Colors.BOLD}",
    5: Colors.BOLD,
    6: Colors.BOLD,
}


# ── Inline formatter ────────────────────────────────────────────────────


def format_inline(line: str) -> str:
    """Apply all inline markdown patterns to a single line.

    Incomplete spans (e.g. ``**bold`` without closing ``**``) are
    left as raw text — this is what makes the streaming
    raw-then-format effect work without writing duplicate text.
    """
    # Bold-italic ***text*** (must run before **bold**)
    line = _BOLD_ITALIC_PAT.sub(
        lambda m: f"{_BOLD_ON}{_ITALIC_ON}{m.group(1)}{_ITALIC_OFF}{_BOLD_OFF}",
        line,
    )
    # Bold **text**
    line = _BOLD_PAT.sub(
        lambda m: f"{_BOLD_ON}{m.group(1)}{_BOLD_OFF}",
        line,
    )
    # Strikethrough ~~text~~
    line = _STRIKE_PAT.sub(
        lambda m: f"{_STRIKE_ON}{m.group(1)}{_STRIKE_OFF}",
        line,
    )
    # Inline code `text`
    line = _INLINE_CODE_PAT.sub(
        lambda m: f"{_CODE_BG}{_CODE_FG}{m.group(1)}{_CODE_OFF}",
        line,
    )
    # Italic *text*  (after bold to avoid matching ** fragments)
    line = _ITALIC_PAT.sub(
        lambda m: f"{_ITALIC_ON}{m.group(1)}{_ITALIC_OFF}",
        line,
    )
    # Links [text](url)
    line = _LINK_PAT.sub(
        lambda m: f"{_LINK_STYLE}{m.group(1)}{_LINK_OFF}",
        line,
    )
    return line


# ── Renderer ────────────────────────────────────────────────────────────


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
        self._state: State = NormalState()
        self._in_thinking: bool = False

    # ── Lifecycle ───────────────────────────────────────────────────

    def on_response_begin(self) -> None:
        self._line_buf = ""
        self._last_formatted = ""
        self._term_width = shutil.get_terminal_size().columns
        self._trailing_lines = 0
        self._state = NormalState()
        self._in_thinking = False

    def on_response_complete(self) -> None:
        self._in_thinking = False

        # Flush any open block state (fence, blockquote, table)
        result = self._state.flush(self._term_width)
        if result is not None:
            self._apply_result(result, "")

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

    # ── Complete line dispatch ─────────────────────────────────────

    def _apply_result(self, result: LineResult, raw_line: str) -> None:
        """Execute the I/O actions described by a ``LineResult``,
        then transition state if requested.

        If the result has ``consumed=False``, the *raw_line* is
        re-dispatched to the new state.
        """
        # 1. Write body text from column 0
        if result.body:
            self._emit_line(result.body)

        # 2. Redraw a block (fence close, blockquote end, table end)
        if result.redraw_target is not None:
            sys.stdout.write(
                screen_utils.overwrite_block(
                    result.previous_screen_rows,
                    result.redraw_target,
                    self._term_width,
                )
            )
            sys.stdout.flush()

        # 3. Transition state
        if result.new_state is not None:
            self._state = result.new_state()
            self._state.on_enter(raw_line, self._term_width)

        # 4. Line not consumed — re-dispatch to the new state
        if not result.consumed:
            self._emit_complete_line(raw_line)

    def _emit_complete_line(self, raw_line: str) -> None:
        """Finalize a complete line (a ``\\n`` just arrived).

        The trailing formatted text from the previous
        ``_rerender_trailing()`` call may span multiple terminal
        rows, so we move the cursor up first, then dispatch to
        the current state machine.
        """
        self._cursor_up_trailing()
        result = self._state.handle_line(raw_line, self._term_width)
        self._apply_result(result, raw_line)

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

    # ── Normal line formatting ─────────────────────────────────────

    def _format_normal_line(self, raw_line: str) -> str:
        """Return the ANSI-formatted version of a normal line."""
        if _HR_PAT.match(raw_line):
            return f"{_DIM}{'─' * self._term_width}{_RESET}"

        hm = _HEADING_PAT.match(raw_line)
        if hm:
            level = len(hm.group(1))
            text = format_inline(hm.group(2))
            color = _HEADING_COLORS.get(level, Colors.BOLD)
            return f"{color}{text}{_RESET}"

        ulm = _UNORDERED_LIST_PAT.match(raw_line)
        if ulm:
            indent = ulm.group(1)
            bullet = ulm.group(2)
            text = format_inline(ulm.group(3))
            return f"{indent}{Colors.ACCENT}{bullet}{_RESET} {text}"

        olm = _ORDERED_LIST_PAT.match(raw_line)
        if olm:
            indent = olm.group(1)
            num = olm.group(2)
            text = format_inline(olm.group(3))
            return f"{indent}{Colors.INFO}{num}{_RESET} {text}"

        return format_inline(raw_line)
