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
        fm = _FENCE_PAT.match(raw_line)
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
        fm = _FENCE_PAT.match(raw_line)
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
            redrawn = self._build_redrawn()
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
        redrawn = self._build_redrawn()
        return LineResult.replace(redrawn, self._screen_rows)

    def _build_redrawn(self) -> list[str]:

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
        col_widths = [3] * ncols
        for row in rows:
            for i, cell in enumerate(row):
                if i < ncols:
                    col_widths[i] = max(col_widths[i], len(cell))

        dim = Colors.DIM
        reset = Colors.RESET

        top = "┌" + "┬".join("─" * (w + 2) for w in col_widths) + "┐"
        mid = "├" + "┼".join("─" * (w + 2) for w in col_widths) + "┤"
        bot = "└" + "┴".join("─" * (w + 2) for w in col_widths) + "┘"

        lines: list[str] = [f"{dim}{top}{reset}"]
        for ri, row in enumerate(rows):
            parts: list[str] = []
            for ci in range(ncols):
                cell = row[ci] if ci < len(row) else ""
                cell_fmt = format_inline(cell)
                cell_vw = screen_utils.visual_width(cell_fmt)
                pad = col_widths[ci] - cell_vw
                parts.append(f" {cell_fmt}{' ' * pad} ")
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
