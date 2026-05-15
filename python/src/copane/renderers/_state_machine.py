"""
State machine for line-level block types in RawReplaceRenderer.

Each state is a pure data container with a ``handle_line()`` method
that returns a ``LineResult`` describing what the renderer should do.
The renderer owns all I/O — states only compute.

A new block type (e.g. ``<details>``, admonitions) is one new state
class and a three-line addition to ``NormalState`` — no boolean flags,
no new flush methods on the renderer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from copane import screen_utils
from copane.term_styles import Colors
from copane.renderers._inline_formatting import format_inline
if TYPE_CHECKING:
    from copane.renderers.raw_replace_renderer import RawReplaceRenderer

# ── Shared patterns ─────────────────────────────────────────────────────

_FENCE_PAT = re.compile(r"^(```|~~~)\s*(\S*)$")
_BQ_PAT = re.compile(r"^(>\s?)(.*)$")
_TABLE_ROW_PAT = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP_PAT = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")
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


# ── Result type ─────────────────────────────────────────────────────────


@dataclass
class LineResult:
    """Returned by ``State.handle_line()``.

    Fields
    ------
    body : str | None
        Text to write from column 0 followed by ``\\n``.
        The state has already decided whether it's raw or
        pre-formatted — the renderer just writes it.
    redraw_target : list[str] | None
        Replace the last ``previous_screen_rows`` rows on screen
        with these lines (via ``overwrite_block()``).
    previous_screen_rows : int
        Number of screen rows that the raw text being replaced
        occupied.  Only meaningful when ``redraw_target`` is set.
    replay_line : str | None
        If set, the renderer will re-dispatch this line to the
        current state (after applying any redraw).  Used by block
        states when they end and a non-block line needs to be
        re-processed by ``NormalState``.
    """

    body: str | None = None
    redraw_target: list[str] | None = None
    previous_screen_rows: int = 0
    replay_line: str | None = None

    # ── Convenience constructors ──────────────────────────────────

    @staticmethod
    def ok() -> LineResult:
        """Line consumed, no I/O needed."""
        return LineResult()

    @staticmethod
    def write(text: str) -> LineResult:
        """Write *text* from column 0."""
        return LineResult(body=text)

    @staticmethod
    def replace(lines: list[str], previous_rows: int,
                replay: str | None = None) -> LineResult:
        """Replace *previous_rows* screen rows with *lines*.

        If *replay* is set, re-dispatch that line after redraw.
        """
        return LineResult(
            redraw_target=lines,
            previous_screen_rows=previous_rows,
            replay_line=replay,
        )


# ── State base ──────────────────────────────────────────────────────────


class State:
    """Base class for a single state in the line-processing machine.

    Subclasses override ``handle_line()``.  The renderer stores the
    current state as ``self._state`` and calls ``handle_line()`` for
    every complete ``\\n``-terminated line.

    Persistent accumulator state (e.g. accumulated raw lines, screen
    row count) is stored as instance attributes on the subclass.

    States receive a reference to the renderer context on
    construction.  They call ``self.ctx.transition_to(StateClass)``
    to switch states — this is the textbook State pattern.
    """

    def __init__(self, ctx: RawReplaceRenderer) -> None:
        self.ctx: RawReplaceRenderer = ctx 

    def handle_line(self, raw_line: str, term_width: int, /) -> LineResult:
        raise NotImplementedError

    def on_enter(self, raw_line: str, term_width: int, /) -> LineResult:
        """Called once when this state becomes active, with the line
        that triggered the transition.

        Default implementation forwards to ``handle_line()``.
        Override when the first line needs different handling
        (e.g. discarding the fence marker from accumulated lines).
        """
        return self.handle_line(raw_line, term_width)

    def flush(self, term_width: int, /) -> LineResult | None:
        """Called at the end of the response to flush any remaining
        accumulated content.

        Override in states that buffer lines (fence, blockquote,
        table) to return a redraw result.  NormalState has nothing
        to flush and returns ``None``.
        """
        return None


# ═══════════════════════════════════════════════════════════════════════
# Normal state  (catch-all dispatcher)
# ═══════════════════════════════════════════════════════════════════════


class NormalState(State):
    """Default state — no open block.

    Routes lines to the appropriate block state or emits them as
    formatted normal lines.
    """

    def handle_line(self, raw_line: str, term_width: int, /) -> LineResult:
        # ── Fence ────────────────────────────────────────────
        fm = _FENCE_PAT.match(raw_line.lstrip())
        if fm:
            return self._switch_to(FenceState, raw_line, term_width)

        # ── Blockquote ───────────────────────────────────────
        bqm = _BQ_PAT.match(raw_line)
        if bqm:
            return self._switch_to(BlockquoteState, raw_line, term_width)

        # ── Table ────────────────────────────────────────────
        if _TABLE_ROW_PAT.match(raw_line):
            return self._switch_to(TableState, raw_line, term_width)

        # ── Normal line ──────────────────────────────────────
        return LineResult(body=self._format_normal(raw_line, term_width))

    def _switch_to(self, new_state_cls: type[State], raw_line: str, term_width: int) -> LineResult:
        """Transition to *new_state_cls* and calls its ``setup()`` with *raw_line*."""
        new_state = new_state_cls(self.ctx)
        result = new_state.on_enter(raw_line, term_width)
        self.ctx.set_state(new_state)
        return result

    # ── Formatting helpers ───────────────────────────────────

    @staticmethod
    def _format_normal(raw_line: str, term_width: int) -> str:
        """Return the ANSI-formatted version of a non-block line."""

        if _HR_PAT.match(raw_line):
            dim = Colors.DIM
            return f"{dim}{'─' * term_width}{Colors.RESET}"

        hm = _HEADING_PAT.match(raw_line)
        if hm:
            level = len(hm.group(1))
            text = format_inline(hm.group(2))
            color = _HEADING_COLORS.get(level, Colors.BOLD)
            return f"{color}{text}{Colors.RESET}"

        ulm = _UNORDERED_LIST_PAT.match(raw_line)
        if ulm:
            indent = ulm.group(1)
            bullet = ulm.group(2)
            text = format_inline(ulm.group(3))
            return f"{indent}{Colors.ACCENT}{bullet}{Colors.RESET} {text}"

        olm = _ORDERED_LIST_PAT.match(raw_line)
        if olm:
            indent = olm.group(1)
            num = olm.group(2)
            text = format_inline(olm.group(3))
            return f"{indent}{Colors.INFO}{num}{Colors.RESET} {text}"

        return format_inline(raw_line)


# ═══════════════════════════════════════════════════════════════════════
# Fence state
# ═══════════════════════════════════════════════════════════════════════


class FenceState(State):
    """Inside a fenced code block (``` or ~~~).

    Accumulates raw lines.  On close, computes the redrawn box and
    returns it as a ``redraw_target``.  On any non-close line,
    returns the raw line for screen output.
    """

    def __init__(self, ctx: RawReplaceRenderer) -> None:
        super().__init__(ctx)
        self._marker: str = ""
        self._lang: str = ""
        self._raw_lines: list[str] = []
        self._screen_rows: int = 0

    def on_enter(self, raw_line: str, term_width: int, /) -> LineResult:
        fm = _FENCE_PAT.match(raw_line)
        self._marker = fm.group(1) if fm else "```"
        self._lang = fm.group(2) if fm else ""
        self._screen_rows += 1  # for the opening fence line
        return LineResult(body=raw_line)

    def handle_line(self, raw_line: str, term_width: int, /) -> LineResult:
        fm = _FENCE_PAT.match(raw_line.lstrip())
        if fm and fm.group(1) == self._marker:
            # ── Fence closed → compute redraw, return to NormalState ──
            redrawn = self._build_redrawn(term_width)
            self.ctx.set_state(NormalState(self.ctx))
            return LineResult.replace(redrawn, self._screen_rows)

        # ── Content line inside fence ─────────────────────
        self._raw_lines.append(raw_line)
        self._screen_rows += screen_utils.screen_lines(raw_line, term_width)
        return LineResult(body=raw_line)

    def flush(self, term_width: int, /) -> LineResult | None:
        """Response ended with unfinished fence — redraw what we have."""
        if not self._raw_lines:
            return None
        redrawn = self._build_redrawn(term_width)
        return LineResult.replace(redrawn, self._screen_rows)

    def _build_redrawn(self, term_width: int) -> list[str]:
        dim = Colors.DIM
        reset = Colors.RESET
        lang_str = f" {self._lang}" if self._lang else ""
        w = term_width

        header = f"{dim}┌──{lang_str} {'─' * max(2, w - 8 - len(lang_str))}{reset}"
        footer = f"{dim}└──{'─' * max(2, w - 6)}{reset}"

        lines: list[str] = [header]
        for raw in self._raw_lines:
            lines.append(f"{dim}│ {raw}{reset}")
        lines.append(footer)
        return lines


# ═══════════════════════════════════════════════════════════════════════
# Blockquote state
# ═══════════════════════════════════════════════════════════════════════


class BlockquoteState(State):
    """Inside a blockquote (``>`` prefix lines).

    Accumulates raw lines until a non-``>`` line arrives, then returns
    a redraw with ``│`` prefix styling.
    """

    def __init__(self, ctx: RawReplaceRenderer) -> None:
        super().__init__(ctx)
        self._raw_lines: list[str] = []
        self._screen_rows: int = 0

    def handle_line(self, raw_line: str, term_width: int, /) -> LineResult:
        bqm = _BQ_PAT.match(raw_line)
        if bqm:
            self._raw_lines.append(raw_line)
            self._screen_rows += screen_utils.screen_lines(raw_line, term_width)
            return LineResult(body=raw_line)

        # ── Blockquote ended — redraw, replay current line to NormalState ──
        if self._raw_lines:
            redrawn = self._build_redrawn()
            self.ctx.set_state(NormalState(self.ctx))
            return LineResult.replace(redrawn, self._screen_rows,
                                       replay=raw_line)
        return LineResult.ok()

    def flush(self, term_width: int, /) -> LineResult | None:
        """Response ended with unfinished blockquote — redraw what we have."""
        if not self._raw_lines:
            return None
        redrawn = self._build_redrawn()
        return LineResult.replace(redrawn, self._screen_rows)

    def _build_redrawn(self) -> list[str]:

        dim = Colors.DIM
        reset = Colors.RESET
        lines: list[str] = []
        for raw in self._raw_lines:
            bqm = _BQ_PAT.match(raw)
            if bqm:
                lines.append(f"{dim}│{reset} {format_inline(bqm.group(2))}")
            else:
                lines.append(f"{dim}│{reset} {raw}")
        return lines


# ═══════════════════════════════════════════════════════════════════════
# Table state
# ═══════════════════════════════════════════════════════════════════════

def _word_wrap(text: str, max_width: int) -> list[str]:
     """Word-wrap *text* (which may contain ANSI codes) so that each
     visual line fits within *max_width* cells.

     ANSI codes are preserved on the first line; subsequent lines get
     only the ANSI reset code.
     """
     if max_width < 1:
         return [text]

     # Split on spaces for word-wrapping
     words = re.split(r'(\s+)', text)
     lines: list[str] = []
     current: list[str] = []
     current_vw = 0

     for word in words:
         word_vw = screen_utils.visual_width(word)
         if current_vw + word_vw > max_width and current:
             lines.append("".join(current).rstrip())
             current = []
             current_vw = 0
         current.append(word)
         current_vw += word_vw

     if current:
         lines.append("".join(current).rstrip())

     return lines if lines else [""]

class TableState(State):
    """Inside a pipe-delimited table.

    Accumulates raw rows until a non-``|`` line arrives, then returns
    a redraw with aligned columns and Unicode box borders.

    A separator row (``|---|---|``) must be present for the table to
    be confirmed.  Unconfirmed tables are left as raw pipes.
    """

    def __init__(self, ctx: RawReplaceRenderer) -> None:
        super().__init__(ctx)
        self._raw_lines: list[str] = []
        self._screen_rows: int = 0
        self._has_sep: bool = False

    def handle_line(self, raw_line: str, term_width: int, /) -> LineResult:
        if _TABLE_ROW_PAT.match(raw_line):
            if _TABLE_SEP_PAT.match(raw_line):
                self._has_sep = True
            self._raw_lines.append(raw_line)
            self._screen_rows += screen_utils.screen_lines(raw_line, term_width)
            return LineResult(body=raw_line)

        # ── Table ended ───────────────────────────────────
        self.ctx.set_state(NormalState(self.ctx))

        if self._raw_lines and self._has_sep:
            redrawn = self._build_redrawn(term_width)
            result = LineResult.replace(redrawn, self._screen_rows,
                                        replay=raw_line)
        else:
            result = LineResult(replay_line=raw_line)

        self._raw_lines = []
        self._screen_rows = 0
        self._has_sep = False
        return result

    def flush(self, term_width: int, /) -> LineResult | None:
        """Response ended with unfinished table — redraw if confirmed."""
        if not self._raw_lines or not self._has_sep:
            return None
        redrawn = self._build_redrawn(term_width)
        return LineResult.replace(redrawn, self._screen_rows)

    def _build_redrawn(self, term_width: int) -> list[str]:
        # Parse rows (skip separator lines)
        rows: list[list[str]] = []
        for raw in self._raw_lines:
            if _TABLE_SEP_PAT.match(raw):
                continue
            cells = [c.strip() for c in raw.split("|")][1:-1]
            rows.append(cells)
    
        if not rows:
            return []
    
        ncols = max(len(r) for r in rows)
    
        # ── Compute initial visual widths ──
        # Use visual_width (which strips ANSI), NOT len(),
        # so inline formatting doesn't misalign columns.
        col_widths = [3] * ncols
        for row in rows:
            for i, cell in enumerate(row):
                if i < ncols:
                    col_widths[i] = max(col_widths[i], screen_utils.visual_width(cell))
    
        # ── Clamp total width to terminal ──
        # Total = (ncols + 1) borders + sum(col_widths + 2 padding per col)
        border_chars = ncols + 1
        total_w = border_chars + sum(w + 2 for w in col_widths)
        if total_w > self.ctx._term_width:
            # Distribute the overflow across the widest columns first
            overflow = total_w - term_width 
            # Sort indices by width descending
            sorted_idx = sorted(range(ncols), key=lambda i: col_widths[i], reverse=True)
            for idx in sorted_idx:
                reduction = min(col_widths[idx] - 1, overflow)  # don't go below 1
                col_widths[idx] -= reduction
                overflow -= reduction
                if overflow <= 0:
                    break
            # Recompute total (should now fit)
            total_w = border_chars + sum(w + 2 for w in col_widths)
    
        # ── Word-wrap cell content ──
        # For each row, wrap each cell to col_width, producing
        # a list of "sub-rows" (one list of segments per sub-row).
        wrapped_rows: list[list[list[str]]] = []
        max_subrows = 1
        for row in rows:
            sub_rows: list[list[str]] = [[] for _ in range(ncols)]
            max_here = 1
            for ci in range(ncols):
                cell = row[ci] if ci < len(row) else ""
                fmt_cell = format_inline(cell)
                max_w = col_widths[ci]
                lines = _word_wrap(fmt_cell, max_w)
                sub_rows[ci] = lines
                max_here = max(max_here, len(lines))
            wrapped_rows.append(sub_rows)
            max_subrows = max(max_subrows, max_here)
    
        dim = Colors.DIM
        reset = Colors.RESET
    
        # ── Box borders ──
        top = "┌" + "┬".join("─" * (w + 2) for w in col_widths) + "┐"
        mid = "├" + "┼".join("─" * (w + 2) for w in col_widths) + "┤"
        bot = "└" + "┴".join("─" * (w + 2) for w in col_widths) + "┘"
    
        lines: list[str] = [f"{dim}{top}{reset}"]
        for ri, sub_cols in enumerate(wrapped_rows):
            # Get the max sub-rows for this row
            n_sub = max(len(sc) for sc in sub_cols)
            for sub_i in range(n_sub):
                parts: list[str] = []
                for ci in range(ncols):
                    cell_lines = sub_cols[ci]
                    cell_text = cell_lines[sub_i] if sub_i < len(cell_lines) else ""
                    cell_vw = screen_utils.visual_width(cell_text)
                    pad = col_widths[ci] - cell_vw
                    parts.append(f" {cell_text}{' ' * pad} ")
                line = (
                    f"{dim}│{reset}"
                    + f"{dim}│{reset}".join(parts)
                    + f"{dim}│{reset}"
                )
                lines.append(line)
            if ri == 0:
                lines.append(f"{dim}{mid}{reset}")
        lines.append(f"{dim}{bot}{reset}")
        return lines

#     def _build_redrawn(self, term_width: int) -> list[str]:
#         # ── 1. Parse ────────────────────────────────────────────────────
#         rows = self._parse_table_rows()
#         if not rows:
#             return []
#    
#         ncols = self._ncols(rows)
#    
#         # ── 2. Compute target column widths ─────────────────────────────
#         col_widths = self._compute_col_widths(rows, ncols, term_width)
#    
#         # ── 3. Word-wrap every cell to fit its column width ─────────────
#         wrapped = self._wrap_cells(rows, ncols, col_widths)
#    
#         # ── 4. Render the table ─────────────────────────────────────────
#         return self._render_table(wrapped, ncols, col_widths)
# 
#     def _parse_table_rows(self) -> list[list[str]]:
#         """Parse raw pipe-delimited lines into cell lists, skipping separators."""
#         rows: list[list[str]] = []
#         for raw in self._raw_lines:
#             if _TABLE_SEP_PAT.match(raw):
#                 continue
#             cells = [c.strip() for c in raw.split("|")][1:-1]
#             rows.append(cells)
#         return rows
#    
#     @staticmethod
#     def _ncols(rows: list[list[str]]) -> int:
#         return max(len(r) for r in rows)
#    
#     def _compute_col_widths(self, rows: list[list[str]], ncols: int, term_width: int) -> list[int]:
#         """Compute column widths that fit within `term_width`.
#    
#         Strategy:
#         1. Start with natural content widths (ANSI-aware).
#         2. If total fits, use them as-is.
#         3. If not, distribute the deficit proportionally across columns,
#            never going below MIN_COL_WIDTH.
#         """
#         MIN_COL_WIDTH = 4
#    
#         # Natural widths
#         widths = [MIN_COL_WIDTH] * ncols
#         for row in rows:
#             for i, cell in enumerate(row):
#                 if i < ncols:
#                     widths[i] = max(widths[i], screen_utils.visual_width(cell))
#    
#         # Check if we need to shrink
#         border_chars = ncols + 1
#         total_w = border_chars + sum(w + 2 for w in widths)
#         if total_w <= term_width:
#             return widths
#    
#         # ── Shrink proportionally ────────────────────────────────
#         available_data = term_width - border_chars - 2 * ncols
#         if available_data < MIN_COL_WIDTH * ncols:
#             # Emergency: too many columns to even show minimum — equal share
#             per_col = max(1, available_data // ncols)
#             return [per_col] * ncols
#    
#         raw_total = sum(widths)
#         new_widths = [max(MIN_COL_WIDTH, w * available_data // raw_total) for w in widths]
#         # Distribute rounding leftovers
#         diff = available_data - sum(new_widths)
#         for i in range(diff):
#             new_widths[i % ncols] += 1
#         return new_widths
#    
#     def _wrap_cells(self, rows: list[list[str]], ncols: int, col_widths: list[int]) -> list[list[list[str]]]:
#         """Word-wrap every cell in every row to its column width.
#    
#         Returns a 3-level structure: rows → columns → wrapped-lines.
#         """
#         wrapped_rows: list[list[list[str]]] = []
#         for row in rows:
#             sub_cols: list[list[str]] = []
#             for ci in range(ncols):
#                 cell = row[ci] if ci < len(row) else ""
#                 fmt_cell = format_inline(cell)
#                 wrapped = _word_wrap(fmt_cell, col_widths[ci])
#                 sub_cols.append(wrapped)
#             wrapped_rows.append(sub_cols)
#         return wrapped_rows
#    
#     def _render_table(self, wrapped: list[list[list[str]]], ncols: int, col_widths: list[int]) -> list[str]:
#         """Build the styled table lines from wrapped cell content."""
#         dim = Colors.DIM
#         reset = Colors.RESET
#    
#         top = "┌" + "┬".join("─" * (w + 2) for w in col_widths) + "┐"
#         mid = "├" + "┼".join("─" * (w + 2) for w in col_widths) + "┤"
#         bot = "└" + "┴".join("─" * (w + 2) for w in col_widths) + "┘"
#    
#         lines: list[str] = [f"{dim}{top}{reset}"]
#         for ri, row in enumerate(wrapped):
#             n_sub = max(len(cell_lines) for cell_lines in row)
#             for sub_i in range(n_sub):
#                 parts: list[str] = []
#                 for ci in range(ncols):
#                     cell_lines = row[ci]
#                     text = cell_lines[sub_i] if sub_i < len(cell_lines) else ""
#                     pad = col_widths[ci] - screen_utils.visual_width(text)
#                     parts.append(f" {text}{' ' * pad} ")
#                 line = (
#                     f"{dim}│{reset}"
#                     + f"{dim}│{reset}".join(parts)
#                     + f"{dim}│{reset}"
#                 )
#                 lines.append(line)
#             if ri == 0:
#                 lines.append(f"{dim}{mid}{reset}")
#         lines.append(f"{dim}{bot}{reset}")
#         return lines
 

