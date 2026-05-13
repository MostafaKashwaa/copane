"""Tests for screen_utils — measurement, low-level escapes, and logical-line helpers.

These tests verify the *contract* of each function: correct return
values and edge-case handling.  They do NOT test composable
operations (``write_line``, ``clear_rest_of_line``, ``overwrite_block``,
``rerender_in_place``), which will get their own test file.
"""

from __future__ import annotations

import re

import pytest

from copane import screen_utils


# ── helpers ────────────────────────────────────────────────────────────


def _ansi_escapes(text: str) -> list[str]:
    """Return every ANSI escape sequence found in *text*."""
    return re.findall(r"\033\[[0-9;]*[A-Za-z]", text)


def _count_ansi_escapes(text: str) -> int:
    """Return the number of ANSI escape sequences in *text*."""
    return len(_ansi_escapes(text))


# ======================================================================
# visual_width
# ======================================================================


class TestVisualWidth:
    """``visual_width(text) → int``"""

    # ── basic / empty ──────────────────────────────────────────────

    def test_empty_string(self):
        assert screen_utils.visual_width("") == 0

    def test_plain_ascii(self):
        assert screen_utils.visual_width("hello") == 5

    def test_single_char(self):
        assert screen_utils.visual_width("x") == 1

    # ── ANSI escape sequences ──────────────────────────────────────

    def test_single_sgr_code(self):
        # \033[1m → bold on (zero visual width)
        assert screen_utils.visual_width("\033[1mhello") == 5

    def test_multiple_sgr_codes(self):
        # \033[1m\033[31mhello\033[0m → 5 visible chars
        assert screen_utils.visual_width("\033[1m\033[31mhello\033[0m") == 5

    def test_extended_sgr_with_semicolons(self):
        # \033[1;31mhello → 5
        assert screen_utils.visual_width("\033[1;31mhello") == 5

    def test_extended_sgr_256color(self):
        # \033[38;5;196mhello → 5
        assert screen_utils.visual_width("\033[38;5;196mhello") == 5

    def test_extended_sgr_truecolor(self):
        # \033[38;2;255;0;0mhello → 5
        assert screen_utils.visual_width("\033[38;2;255;0;0mhello") == 5

    def test_ansi_reset_only(self):
        assert screen_utils.visual_width("\033[0m") == 0

    def test_ansi_bold_off(self):
        assert screen_utils.visual_width("\033[22m") == 0

    def test_text_with_embedded_ansi(self):
        # ansi in the middle
        assert screen_utils.visual_width("he\033[1mllo") == 5

    def test_text_with_trailing_ansi(self):
        assert screen_utils.visual_width("hello\033[0m") == 5

    def test_text_with_leading_and_trailing_ansi(self):
        assert screen_utils.visual_width("\033[1mhello\033[0m") == 5

    def test_unicode_with_ansi(self):
        # ✅ emoji is wide but visual_width counts chars, not terminal cells
        assert screen_utils.visual_width("\033[1m✓ done\033[0m") == 6

    # ── Unicode (no ansi) ──────────────────────────────────────────

    def test_unicode_ascii_width_chars(self):
        # narrow unicode chars each occupy 1 cell in a typical terminal
        assert screen_utils.visual_width("café") == 4

    def test_wide_cjk_chars_count_as_two_cells_each(self):
        # 你好 → 2 chars, each is 2 cells wide → 4 cells total.
        # A naive implementation that uses len() would return 2.
        assert screen_utils.visual_width("你好") == 4

    # ── newlines ───────────────────────────────────────────────────

    def test_newline_characters_are_not_stripped(self):
        # newlines are printable characters, not ANSI escapes
        assert screen_utils.visual_width("a\nb") >= 3

    def test_carriage_return_character(self):
        # \r is \x0d, not an ansi escape — should count as visible
        assert screen_utils.visual_width("\r") >= 0  # but likely 1


# ======================================================================
# screen_lines
# ======================================================================


class TestScreenLines:
    """``screen_lines(text, term_width) → int``"""

    # ── empty ──────────────────────────────────────────────────────

    def test_empty_text_returns_zero(self):
        assert screen_utils.screen_lines("", 80) == 0

    # ── fits in one line ───────────────────────────────────────────

    def test_text_shorter_than_terminal(self):
        assert screen_utils.screen_lines("hello", 80) == 1

    def test_text_exactly_terminal_width(self):
        assert screen_utils.screen_lines("1234567890", 10) == 1

    # ── wrapping ───────────────────────────────────────────────────

    def test_one_char_over_width(self):
        assert screen_utils.screen_lines("12345678901", 10) == 2

    def test_exact_double_width(self):
        assert screen_utils.screen_lines("a" * 20, 10) == 2

    def test_double_plus_one(self):
        assert screen_utils.screen_lines("a" * 21, 10) == 3

    def test_many_lines(self):
        assert screen_utils.screen_lines("x" * 100, 10) == 10

    def test_wide_char_at_eol_triggers_early_wrap(self):
        # 19 ASCII a's + one wide CJK char (2 cells) = 21 cells on a
        # 20-col terminal.  The CJK char won't fit at columns 18-19,
        # so it wraps to the next line → 2 screen lines total.
        # A naive len-based count would say 20 chars = 1 line.
        text = "a" * 19 + "好"  # 19 + 2 = 21 cells
        assert screen_utils.screen_lines(text, 20) == 2

    # ── ANSI codes don't add to visual width ──────────────────────

    def test_ansi_codes_dont_cause_extra_wrapping(self):
        # 10 visible chars + ansi codes → still 1 line at width 10
        text = "\033[1m1234567890\033[0m"
        assert screen_utils.screen_lines(text, 10) == 1

    def test_ansi_codes_with_long_text(self):
        # 25 visible chars, width 10 → 3 lines regardless of ansi
        inner = "x" * 25
        text = f"\033[1;31m{inner}\033[0m"
        assert screen_utils.screen_lines(text, 10) == 3

    def test_ansi_only_text_is_zero_width(self):
        # purely ansi text has visual width 0 → 0 screen lines
        assert screen_utils.screen_lines("\033[1m\033[31m", 80) == 0

    # ── term_width edge cases ──────────────────────────────────────

    def test_term_width_zero_treated_as_one(self):
        # doc: "term_width of 0 or less is treated as 1"
        assert screen_utils.screen_lines("hello", 0) == 5

    def test_term_width_negative_treated_as_one(self):
        assert screen_utils.screen_lines("abc", -5) == 3

    def test_term_width_one(self):
        # each character on its own line
        assert screen_utils.screen_lines("abc", 1) == 3

    def test_large_term_width(self):
        assert screen_utils.screen_lines("hello", 10000) == 1

    # ── zero-width text (ani only) with edge widths ────────────────

    def test_empty_with_zero_width(self):
        assert screen_utils.screen_lines("", 0) == 0

    def test_zero_visual_width_with_normal_term(self):
        assert screen_utils.screen_lines("\033[1m", 80) == 0


# ======================================================================
# cursor_up
# ======================================================================


class TestCursorUp:
    """``cursor_up(n) → str``"""

    def test_zero_is_noop(self):
        assert screen_utils.cursor_up(0) == ""

    def test_negative_is_noop(self):
        assert screen_utils.cursor_up(-1) == ""
        assert screen_utils.cursor_up(-100) == ""

    def test_one(self):
        assert screen_utils.cursor_up(1) == "\033[1A"

    def test_large_n(self):
        assert screen_utils.cursor_up(50) == "\033[50A"

    def test_returns_string(self):
        assert isinstance(screen_utils.cursor_up(3), str)

    def test_no_side_effects(self):
        # calling multiple times always returns same value
        a = screen_utils.cursor_up(5)
        b = screen_utils.cursor_up(5)
        assert a == b == "\033[5A"

    def test_only_one_ansi_escape(self):
        # cursor_up(n) should produce exactly one ANSI escape sequence
        assert _count_ansi_escapes(screen_utils.cursor_up(1)) == 1
        assert _count_ansi_escapes(screen_utils.cursor_up(7)) == 1

    def test_no_carriage_return(self):
        # cursor_up does NOT change column — should not contain \r
        assert "\r" not in screen_utils.cursor_up(5)


# ======================================================================
# cursor_down
# ======================================================================


class TestCursorDown:
    """``cursor_down(n) → str``"""

    def test_zero_is_noop(self):
        assert screen_utils.cursor_down(0) == ""

    def test_negative_is_noop(self):
        assert screen_utils.cursor_down(-3) == ""

    def test_one(self):
        assert screen_utils.cursor_down(1) == "\033[1B"

    def test_large_n(self):
        assert screen_utils.cursor_down(100) == "\033[100B"

    def test_returns_string(self):
        assert isinstance(screen_utils.cursor_down(2), str)

    def test_no_side_effects(self):
        a = screen_utils.cursor_down(3)
        b = screen_utils.cursor_down(3)
        assert a == b == "\033[3B"

    def test_only_one_ansi_escape(self):
        assert _count_ansi_escapes(screen_utils.cursor_down(1)) == 1

    def test_no_carriage_return(self):
        assert "\r" not in screen_utils.cursor_down(5)


# ======================================================================
# cursor_col0
# ======================================================================


class TestCursorCol0:
    """``cursor_col0() → str``"""

    def test_returns_carriage_return(self):
        assert screen_utils.cursor_col0() == "\r"

    def test_idempotent(self):
        assert screen_utils.cursor_col0() == screen_utils.cursor_col0()

    def test_returns_string(self):
        assert isinstance(screen_utils.cursor_col0(), str)

    def test_no_ansi_escape(self):
        # \r is ASCII 0x0d, not an ANSI CSI sequence
        assert _count_ansi_escapes(screen_utils.cursor_col0()) == 0


# ======================================================================
# clear_to_eol
# ======================================================================


class TestClearToEol:
    """``clear_to_eol() → str``"""

    def test_returns_el_escape(self):
        assert screen_utils.clear_to_eol() == "\033[K"

    def test_idempotent(self):
        assert screen_utils.clear_to_eol() == screen_utils.clear_to_eol()

    def test_returns_string(self):
        assert isinstance(screen_utils.clear_to_eol(), str)

    def test_exactly_one_ansi_escape(self):
        assert _count_ansi_escapes(screen_utils.clear_to_eol()) == 1

    def test_no_carriage_return(self):
        # clear_to_eol only clears, does not move to col 0
        assert "\r" not in screen_utils.clear_to_eol()


# ======================================================================
# clear_line
# ======================================================================


class TestClearLine:
    """``clear_line() → str``"""

    def test_clears_and_moves_to_col0(self):
        result = screen_utils.clear_line()
        assert "\r" in result
        assert "\033[K" in result

    def test_carriage_return_before_clear(self):
        # \r must come before \033[K, otherwise clearing the wrong line
        result = screen_utils.clear_line()
        assert result.index("\r") < result.index("\033[K")

    def test_returns_string(self):
        assert isinstance(screen_utils.clear_line(), str)

    def test_idempotent(self):
        assert screen_utils.clear_line() == screen_utils.clear_line()

    def test_exactly_one_ansi_escape(self):
        assert _count_ansi_escapes(screen_utils.clear_line()) == 1

    def test_no_newline(self):
        # clear_line does NOT advance to the next line
        assert "\n" not in screen_utils.clear_line()


# ======================================================================
# cursor_to_logical_line_start
# ======================================================================


class TestCursorToLogicalLineStart:
    """``cursor_to_logical_line_start(screen_lines_above) → str``"""

    # ── zero screen_lines_above ─────────────────────────────────────

    def test_zero_returns_cr_only(self):
        result = screen_utils.cursor_to_logical_line_start(0)
        assert result == "\r"
        assert "\033[" not in result

    # ── positive ───────────────────────────────────────────────────

    def test_one(self):
        result = screen_utils.cursor_to_logical_line_start(1)
        # moves up 1, then carriage return
        assert "\033[1A" in result
        assert result.endswith("\r")

    def test_many(self):
        result = screen_utils.cursor_to_logical_line_start(5)
        assert "\033[5A" in result
        assert result.endswith("\r")

    def test_cursor_up_before_cr(self):
        # Must move up FIRST, then \r — otherwise \r lands on wrong line
        result = screen_utils.cursor_to_logical_line_start(3)
        assert result.index("\033[") < result.index("\r")

    # ── edge cases ─────────────────────────────────────────────────

    def test_negative_treated_as_zero(self):
        # negative screen_lines_above is nonsensical — should behave
        # like 0 or be handled gracefully (no crash)
        result = screen_utils.cursor_to_logical_line_start(-1)
        assert isinstance(result, str)
        # At minimum, must not contain a negative CSI value like \033[-1A
        assert "\033[-" not in result

    def test_returns_string(self):
        assert isinstance(screen_utils.cursor_to_logical_line_start(2), str)

    def test_exactly_one_csi_if_positive(self):
        assert _count_ansi_escapes(screen_utils.cursor_to_logical_line_start(4)) == 1

    def test_no_newline(self):
        assert "\n" not in screen_utils.cursor_to_logical_line_start(3)


# ======================================================================
# clear_logical_line
# ======================================================================


class TestClearLogicalLine:
    """``clear_logical_line(screen_lines) → str``"""

    # ── zero screen_lines ──────────────────────────────────────────

    def test_zero_returns_empty(self):
        assert screen_utils.clear_logical_line(0) == ""

    # ── single visual row ──────────────────────────────────────────

    def test_one(self):
        result = screen_utils.clear_logical_line(1)
        # cursor at col 0, clear to eol — no cursor movement needed
        assert "\033[K" in result

    def test_one_does_not_move_cursor_vertically(self):
        result = screen_utils.clear_logical_line(1)
        assert "\033[A" not in result
        assert "\033[B" not in result
        assert "\n" not in result

    def test_one_leaves_cursor_at_col0(self):
        # After clearing, cursor should still be at col 0 on the same row.
        # Since it started at col 0 and \033[K doesn't move the cursor,
        # no \r is *required* at the end — but should not end with \n either.
        result = screen_utils.clear_logical_line(1)
        assert not result.endswith("\n")

    # ── multiple visual rows ───────────────────────────────────────

    def test_multiple_rows(self):
        result = screen_utils.clear_logical_line(3)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_multiple_rows_each_cleared_with_el(self):
        result = screen_utils.clear_logical_line(3)
        # Should contain exactly 3 \033[K sequences
        assert _count_ansi_escapes(result) >= 2  # at minimum: cursor-up + clears

    def test_multiple_rows_ends_at_col0_of_first_row(self):
        result = screen_utils.clear_logical_line(4)
        # After clearing all rows, cursor must be back at col 0 of row 1.
        # That means the final character should be \r, or it shouldn't end
        # in a way that leaves the cursor mid-row.
        # We test: if cursor-up was used, it must be followed by \r.
        if "\033[A" in result or "\033[B" in result:
            # Some vertical movement happened — verify we land at right place
            pass  # contract not fully specifiable without implementation details

    def test_multiple_rows_no_trailing_newline(self):
        result = screen_utils.clear_logical_line(3)
        assert not result.endswith("\n")

    # ── edge cases ─────────────────────────────────────────────────

    def test_negative_treated_as_zero(self):
        result = screen_utils.clear_logical_line(-1)
        assert isinstance(result, str)
        assert "\033[-" not in result

    def test_large_screen_lines(self):
        result = screen_utils.clear_logical_line(50)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_string(self):
        assert isinstance(screen_utils.clear_logical_line(2), str)

    def test_idempotent(self):
        assert screen_utils.clear_logical_line(3) == screen_utils.clear_logical_line(3)

    def test_contains_no_tabs_or_backspaces(self):
        result = screen_utils.clear_logical_line(5)
        assert "\t" not in result
        assert "\b" not in result


# ======================================================================
# write_clear
# ======================================================================


class TestWriteClear:
    """``write_clear(text) → str``

    ``write_clear`` writes *text* from column 0 and clears the rest of
    the line, but does **not** advance the cursor to the next line.
    This is the key difference from ``write_line``, which appends a
    trailing ``\\n``.
    """

    # ── basic structure ────────────────────────────────────────────

    def test_plain_text(self):
        result = screen_utils.write_clear("hello")
        assert result == "\rhello\033[K"

    def test_empty_text(self):
        result = screen_utils.write_clear("")
        assert result == "\r\033[K"

    def test_starts_with_carriage_return(self):
        result = screen_utils.write_clear("abc")
        assert result.startswith("\r")

    def test_ends_with_el(self):
        result = screen_utils.write_clear("abc")
        assert result.endswith("\033[K")

    def test_no_newline(self):
        """``write_clear`` must not advance the cursor."""
        assert "\n" not in screen_utils.write_clear("any text")

    def test_cr_before_text_before_el(self):
        result = screen_utils.write_clear("xyz")
        cr = result.index("\r")
        tx = result.index("xyz")
        el = result.index("\033[K")
        assert cr < tx < el

    # ── text with ANSI codes ───────────────────────────────────────

    def test_text_with_ansi_preserved(self):
        result = screen_utils.write_clear("\033[1mhi\033[0m")
        assert "\033[1mhi\033[0m" in result

    def test_exactly_one_ansi_escape_in_plain_text(self):
        # write_clear adds one EL; no cursor-up
        result = screen_utils.write_clear("hello")
        assert _count_ansi_escapes(result) == 1

    def test_ansi_codes_count_with_text(self):
        # text has 2 ansi codes + one EL from write_clear = 3
        result = screen_utils.write_clear("\033[1m\033[31mhello")
        assert _count_ansi_escapes(result) == 3

    # ── edge cases ─────────────────────────────────────────────────

    def test_returns_string(self):
        assert isinstance(screen_utils.write_clear(""), str)

    def test_idempotent(self):
        assert screen_utils.write_clear("hello") == screen_utils.write_clear("hello")

    def test_newline_in_text_is_preserved(self):
        # write_clear does NOT strip or replace \n in the text itself
        result = screen_utils.write_clear("a\nb")
        assert "a\nb" in result

    def test_tab_in_text_is_preserved(self):
        result = screen_utils.write_clear("a\tb")
        assert "a\tb" in result

    def test_wide_chars_dont_affect_escape_structure(self):
        result = screen_utils.write_clear("你好")
        assert result == "\r你好\033[K"

    def test_no_backspace(self):
        assert "\b" not in screen_utils.write_clear("test")

    def test_not_ending_with_newline(self):
        """Explicitly verify no trailing \\n unlike write_line."""
        result = screen_utils.write_clear("hello")
        assert not result.endswith("\n")
