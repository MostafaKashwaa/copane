"""
screen_utils — cursor positioning and screen measurement primitives.

Pure functions that return ANSI escape sequences (or measurements)
without side effects.  The caller (e.g. a renderer) is responsible
for writing the returned strings to ``sys.stdout``.

The distinction between *visual lines* and *logical lines* is
important in a terminal:

*   A **logical line** is delimited by ``\\n`` — it's the unit the
    application thinks of as "a line".
*   A **visual line** (also called a *screen row*) is a single row
    on the terminal display.  A logical line that is wider than the
    terminal wraps into multiple visual lines.

All the composable operations below work in terms of **visual lines**
(screen rows), because ANSI cursor-control escapes operate on the
display grid, not on logical lines.
"""

from __future__ import annotations

import re
import unicodedata

# ── ANSI escape stripping ──────────────────────────────────────────────

_ANSI_CSI_RE = re.compile(r"\033\[[0-9;]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    """Remove ANSI CSI escape sequences from *text*."""
    return _ANSI_CSI_RE.sub("", text)


# ── Measurement (no I/O) ───────────────────────────────────────────────


def visual_width(text: str) -> int:
    """Return the display width of *text*, ignoring ANSI escape sequences.

    Wide characters (East Asian Width ``W`` or ``F``) count as 2 cells;
    all other characters count as 1 cell — including control characters
    such as ``\\n`` and ``\\r``.
    """
    plain = _strip_ansi(text)
    total = 0
    for ch in plain:
        ea = unicodedata.east_asian_width(ch)
        total += 2 if ea in ("W", "F") else 1
    return total


def screen_lines(text: str, term_width: int) -> int:
    """Return how many visual lines *text* occupies after wrapping.

    Returns 0 for empty text.  A *term_width* of 0 or less is
    treated as 1 to avoid division errors.
    """
    vw = visual_width(text)
    if vw == 0:
        return 0
    w = max(term_width, 1)
    return (vw + w - 1) // w


# ── Low-level cursor escapes ───────────────────────────────────────────


def cursor_up(n: int) -> str:
    """Escape sequence to move the cursor up *n* visual lines.

    Does **not** change the column.  No-op if *n* ≤ 0.
    """
    if n <= 0:
        return ""
    return f"\033[{n}A"


def cursor_down(n: int) -> str:
    """Escape sequence to move the cursor down *n* visual lines.

    Does **not** change the column.  No-op if *n* ≤ 0.
    """
    if n <= 0:
        return ""
    return f"\033[{n}B"


def cursor_col0() -> str:
    """Escape sequence to move the cursor to column 0 (``\\r``)."""
    return "\r"


def clear_to_eol() -> str:
    """Escape sequence to clear from the cursor to the end of the
    current visual line (``\\033[K``)."""
    return "\033[K"


def clear_line() -> str:
    """Escape sequence to clear the entire current visual line and
    move the cursor to column 0."""
    return "\r\033[K"


# ── Composable line-level operations ───────────────────────────────────


def write_line(text: str) -> str:
    """Escape sequence to write *text* at column 0, clear the rest
    of the visual line, and advance to the next visual line.

    Equivalent to ``\\r{text}\\033[K\\n``.
    """
    return f"\r{text}\033[K\n"


def clear_rest_of_line() -> str:
    """Clear from the cursor to the end of the current visual line
    and advance to the next visual line.

    Equivalent to ``\\033[K\\n``.
    """
    return "\033[K\n"


# ── Internal: splitting logical lines into screen rows ──────────────────


def _is_wide(ch: str) -> bool:
    """Return True if *ch* occupies 2 terminal cells."""
    return unicodedata.east_asian_width(ch) in ("W", "F")


def _split_to_screen_rows(text: str, term_width: int) -> list[str]:
    """Split *text* (without ANSI codes) into screen rows, each
    fitting within *term_width* cells.  Wide characters are never
    split — if a wide char doesn't fit on the current row it moves
    entirely to the next row.
    """
    w = max(term_width, 1)
    rows: list[str] = []
    current: list[str] = []
    current_width = 0

    for ch in text:
        ch_width = 2 if _is_wide(ch) else 1

        if current_width + ch_width > w and current_width > 0:
            rows.append("".join(current))
            current = []
            current_width = 0

        current.append(ch)
        current_width += ch_width

    if current:
        rows.append("".join(current))

    return rows if rows else [""]


def _write_logical_line(text: str, term_width: int) -> str:
    """Write a logical line, splitting into individual ``write_line``
    calls for each screen row the text wraps into.

    When *text* contains ANSI escapes, the function falls back to a
    single ``write_line`` (letting the terminal handle wrapping),
    because mapping ANSI codes across split points is non-trivial.
    """
    sl = screen_lines(text, term_width)
    if sl <= 1:
        return write_line(text)

    # Text wraps.  If it has ANSI, fall back — the terminal will
    # wrap naturally, but intermediate rows might not get cleared.
    if "\033[" in text:
        return write_line(text)

    rows = _split_to_screen_rows(text, term_width)
    return "".join(write_line(r) for r in rows)


# ── Block-level overwrite ──────────────────────────────────────────────


def overwrite_block(
    old_screen_lines: int,
    new_lines: list[str],
    term_width: int,
) -> str:
    """Replace *old_screen_lines* screen rows with *new_lines*.

    Returns an escape sequence that:

    1. Moves the cursor up to the first screen row of the block
       that is currently on screen.
    2. Writes each line in *new_lines* from column 0, clearing to
       end of line.
    3. If *new_lines* occupies fewer screen rows than
       *old_screen_lines*, clears the leftover rows so no stale
       text remains.

    Returns an empty string if there is nothing to overwrite.
    """
    if old_screen_lines <= 0 and not new_lines:
        return ""

    parts: list[str] = []

    if old_screen_lines > 0:
        parts.append(cursor_up(old_screen_lines))

    total_new = 0
    for ln in new_lines:
        parts.append(_write_logical_line(ln, term_width))
        total_new += screen_lines(ln, term_width)

    leftover = old_screen_lines - total_new
    if leftover > 0:
        parts.append(clear_rest_of_line() * leftover)

    return "".join(parts)


# ── In-place re-render (trailing text) ─────────────────────────────────


def rerender_in_place(
    old_text: str,
    old_screen_lines: int,
    new_text: str,
    term_width: int,
) -> tuple[str, int]:
    """Overwrite *old_text* (which occupies *old_screen_lines*
    visual rows) with *new_text* in place — useful for re-rendering
    a trailing incomplete line on every chunk.

    Returns ``(escape_sequence, new_screen_lines)`` where
    *escape_sequence* handles cursor movement, writing, and
    leftover-line clearing, and *new_screen_lines* is the screen
    row count of *new_text* for the caller to store for the next
    invocation.
    """
    new_sl = screen_lines(new_text, term_width)

    if old_screen_lines <= 0 and new_sl == 0:
        return ("", 0)

    parts: list[str] = []

    if old_screen_lines > 0:
        parts.append(cursor_up(old_screen_lines))

    if new_sl > 0:
        parts.append(_write_logical_line(new_text, term_width))

    leftover = old_screen_lines - new_sl
    if leftover > 0:
        parts.append(clear_rest_of_line() * leftover)

    return ("".join(parts), new_sl)


# ── Logical-line cursor helpers ────────────────────────────────────────


def cursor_to_logical_line_start(screen_lines_above: int) -> str:
    """Move the cursor to column 0 of the current logical line,
    given that the cursor is *screen_lines_above* visual rows
    below the start of that logical line.

    Returns ``\\r`` if *screen_lines_above* is 0; otherwise moves
    up *screen_lines_above* rows and then ``\\r``.
    """
    if screen_lines_above <= 0:
        return "\r"
    return f"\033[{screen_lines_above}A\r"


def clear_logical_line(screen_lines: int) -> str:
    """Clear the entire logical line that spans *screen_lines*
    visual rows.  The cursor must be at column 0 of its first
    visual row.

    Clears each visual row from cursor to end-of-line and leaves
    the cursor at column 0 of the first row.
    """
    if screen_lines <= 0:
        return ""
    if screen_lines == 1:
        return "\033[K"
    # Clear rows 1 .. n-1, advance; clear row n, then return to row 1 col 0.
    above = screen_lines - 1
    return ("\033[K\n" * above) + "\033[K" + f"\033[{above}A\r"
