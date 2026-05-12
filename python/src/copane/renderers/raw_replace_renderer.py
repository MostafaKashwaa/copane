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
"""

from __future__ import annotations

import re
import shutil
import sys
from dataclasses import dataclass

from copane import screen_utils
from copane.renderers._base import Renderer
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
_FENCE_PAT = re.compile(r"^(```|~~~)\s*(\S*)$")
_HR_PAT = re.compile(r"^[-*_]{3,}\s*$")
_BQ_PAT = re.compile(r"^(>\s?)(.*)$")
_HEADING_PAT = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_UNORDERED_LIST_PAT = re.compile(r"^(\s*)([-*+])\s+(.+)$")
_ORDERED_LIST_PAT = re.compile(r"^(\s*)(\d+\.)\s+(.+)$")

# Table patterns
_TABLE_ROW_PAT = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP_PAT = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")

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


@dataclass
class _FenceState:
    """Track an open fenced code block for later redraw."""

    header: str              # top box-drawing line
    footer: str              # bottom box-drawing line
    fence_marker: str        # ``` or ~~~
    raw_lines: list[str]     # accumulated raw body lines


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

        # Code fence state
        self._in_code_block: bool = False
        self._fence: _FenceState | None = None

        # Blockquote state
        self._bq_lines: list[str] = []
        self._bq_count: int = 0

        # Table state
        self._table_lines: list[str] = []    # accumulated raw rows (incl. separator)
        self._table_count: int = 0           # screen lines occupied by raw table
        self._table_has_sep: bool = False    # separator row seen → confirmed table

        self._in_thinking: bool = False

    # ── Lifecycle ───────────────────────────────────────────────────

    def on_response_begin(self) -> None:
        self._line_buf = ""
        self._last_formatted = ""
        self._term_width = shutil.get_terminal_size().columns
        self._trailing_lines = 0
        self._in_code_block = False
        self._fence = None
        self._bq_lines = []
        self._bq_count = 0
        self._table_lines = []
        self._table_count = 0
        self._table_has_sep = False
        self._in_thinking = False

    def on_response_complete(self) -> None:
        self._in_thinking = False

        if self._in_code_block and self._fence is not None:
            self._flush_fence()
            self._in_code_block = False
            self._fence = None

        if self._bq_lines:
            self._flush_blockquote()

        if self._table_lines and self._table_has_sep:
            self._flush_table()

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

        self._in_thinking = False
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

    # ── Pending block helpers ──────────────────────────────────────

    def _flush_pending_blocks(self) -> None:
        """Flush any accumulated blockquote or table that hasn't been
        finalised yet.  Safe to call even when no blocks are pending.
        """
        if self._bq_lines:
            self._flush_blockquote()
        if self._table_lines and self._table_has_sep:
            self._flush_table()
        self._table_lines = []
        self._table_count = 0
        self._table_has_sep = False

    # ── Complete line dispatch ─────────────────────────────────────

    def _emit_complete_line(self, raw_line: str) -> None:
        """Finalize a complete line (a ``\\n`` just arrived).

        The trailing formatted text from the previous
        ``_rerender_trailing()`` call may span multiple terminal
        rows, so we move the cursor up first, then overwrite from
        column 0.
        """

        self._cursor_up_trailing()

        # ── Fenced code ────────────────────────────────────────────
        fm = _FENCE_PAT.match(raw_line)
        if fm:
            fence_marker = fm.group(1)
            if not self._in_code_block:
                # Flush any pending table/blockquote before starting a
                # code fence — otherwise they'd leak into the fence or
                # be silently dropped.
                self._flush_pending_blocks()
                self._start_fence(fence_marker, fm.group(2))
                self._write_clear(raw_line)
                sys.stdout.write("\n")
                sys.stdout.flush()
            elif self._fence is not None and self._fence.fence_marker == fence_marker:
                self._trailing_lines = 0
                self._flush_fence()
                self._in_code_block = False
                self._fence = None
            else:
                self._fence.raw_lines.append(raw_line)
                self._write_clear(raw_line)
                sys.stdout.write("\n")
                sys.stdout.flush()
            self._trailing_lines = 0
            return

        if self._in_code_block and self._fence is not None:
            self._fence.raw_lines.append(raw_line)
            self._write_clear(raw_line)
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._trailing_lines = 0
            return

        # ── Blockquote ─────────────────────────────────────────────
        bqm = _BQ_PAT.match(raw_line)
        if bqm:
            # Flush any pending table before starting a blockquote —
            # otherwise a table immediately before a blockquote would
            # be silently dropped.
            if self._table_lines and self._table_has_sep:
                self._flush_table()
            self._table_lines = []
            self._table_count = 0
            self._table_has_sep = False

            self._bq_lines.append(raw_line)
            self._bq_count += screen_utils.screen_lines(raw_line, self._term_width)
            self._write_clear(raw_line)
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._trailing_lines = 0
            return

        # Blockquote ended — flush the accumulated block
        if self._bq_lines:
            self._flush_blockquote()

        # ── Table ──────────────────────────────────────────────────
        if _TABLE_ROW_PAT.match(raw_line):
            if _TABLE_SEP_PAT.match(raw_line):
                self._table_has_sep = True
            self._table_lines.append(raw_line)
            self._table_count += screen_utils.screen_lines(raw_line, self._term_width)
            self._write_clear(raw_line)
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._trailing_lines = 0
            return

        # Table ended (confirmed or not)
        if self._table_lines:
            if self._table_has_sep:
                self._flush_table()
            # If never confirmed, raw lines are already on screen — nothing to do
            self._table_lines = []
            self._table_count = 0
            self._table_has_sep = False

        # ── Normal line ────────────────────────────────────────────
        formatted = self._format_normal_line(raw_line)
        self._write_clear(formatted)
        sys.stdout.write("\n")
        sys.stdout.flush()
        self._trailing_lines = 0

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
        if self._in_code_block:
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
                sys.stdout.write("\n\033[K")
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

    # ── Fenced code blocks ─────────────────────────────────────────

    def _start_fence(self, fence_marker: str, lang: str) -> None:
        self._in_code_block = True
        lang_str = f" {lang}" if lang else ""
        w = self._term_width
        header = f"{_DIM}┌──{lang_str} {'─' * max(2, w - 8 - len(lang_str))}{_RESET}"
        footer = f"{_DIM}└──{'─' * max(2, w - 6)}{_RESET}"
        self._fence = _FenceState(
            header=header,
            footer=footer,
            fence_marker=fence_marker,
            raw_lines=[],
        )

    def _flush_fence(self) -> None:
        """Redraw the accumulated fenced code block with box borders."""
        if self._fence is None:
            return

        # The screen currently shows: fence-marker line + N raw body lines.
        # We'll replace them with: header + styled body lines + footer.
        old_rows = 1 + len(self._fence.raw_lines)  # marker + body

        new_lines: list[str] = [self._fence.header]
        new_lines.extend(
            f"{_DIM}│ {raw}{_RESET}" for raw in self._fence.raw_lines
        )
        new_lines.append(self._fence.footer)

        sys.stdout.write(
            screen_utils.overwrite_block(old_rows, new_lines, self._term_width)
        )
        sys.stdout.flush()

    # ── Blockquote blocks ──────────────────────────────────────────

    def _flush_blockquote(self) -> None:
        """Redraw accumulated blockquote lines with ``│`` prefix."""
        if not self._bq_lines or self._bq_count == 0:
            self._bq_lines = []
            self._bq_count = 0
            return

        new_lines: list[str] = []
        for raw in self._bq_lines:
            bqm = _BQ_PAT.match(raw)
            if bqm:
                new_lines.append(
                    f"{_DIM}│{_RESET} {format_inline(bqm.group(2))}"
                )
            else:
                new_lines.append(f"{_DIM}│{_RESET} {raw}")

        sys.stdout.write(
            screen_utils.overwrite_block(
                self._bq_count, new_lines, self._term_width
            )
        )
        sys.stdout.flush()
        self._bq_lines = []
        self._bq_count = 0

    # ── Table blocks ───────────────────────────────────────────────

    def _flush_table(self) -> None:
        """Redraw accumulated table with aligned columns and box borders.

        The raw pipe-separated rows that are currently on screen are
        replaced with a Unicode box-drawing table where each column
        is padded to the maximum content width.
        """
        if not self._table_lines or self._table_count == 0:
            return

        # Parse rows (skip separator lines, keep header + data)
        rows: list[list[str]] = []
        for raw in self._table_lines:
            if _TABLE_SEP_PAT.match(raw):
                continue
            # "| foo | bar |" → ["foo", "bar"]
            cells = [c.strip() for c in raw.split("|")][1:-1]
            rows.append(cells)

        if not rows:
            return

        ncols = max(len(r) for r in rows)

        # Compute column widths using raw cells (before inline formatting,
        # which only adds ANSI codes with zero visual width).
        col_widths = [3] * ncols
        for row in rows:
            for i, cell in enumerate(row):
                if i < ncols:
                    w = len(cell)
                    if w > col_widths[i]:
                        col_widths[i] = w

        # ── Pre-compute all redrawn lines ──────────────────────────

        top = "┌" + "┬".join("─" * (w + 2) for w in col_widths) + "┐"
        mid = "├" + "┼".join("─" * (w + 2) for w in col_widths) + "┤"
        bot = "└" + "┴".join("─" * (w + 2) for w in col_widths) + "┘"

        redrawn_lines: list[str] = [f"{_DIM}{top}{_RESET}"]

        for ri, row in enumerate(rows):
            parts: list[str] = []
            for ci in range(ncols):
                cell = row[ci] if ci < len(row) else ""
                cell_fmt = format_inline(cell)
                cell_vw = screen_utils.visual_width(cell_fmt)
                pad = col_widths[ci] - cell_vw
                parts.append(f" {cell_fmt}{' ' * pad} ")

            line = (
                f"{_DIM}│{_RESET}"
                + f"{_DIM}│{_RESET}".join(parts)
                + f"{_DIM}│{_RESET}"
            )
            redrawn_lines.append(line)

            # Separator after header row
            if ri == 0:
                redrawn_lines.append(f"{_DIM}{mid}{_RESET}")

        redrawn_lines.append(f"{_DIM}{bot}{_RESET}")

        # ── Cursor up, write redrawn table, clear leftovers ────────

        sys.stdout.write(
            screen_utils.overwrite_block(
                self._table_count, redrawn_lines, self._term_width
            )
        )
        sys.stdout.flush()
