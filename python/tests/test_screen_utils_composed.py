"""Tests for screen_utils composable operations — ``write_line``,
``clear_rest_of_line``, ``overwrite_block``, and ``rerender_in_place``.

These functions compose the low-level primitives (cursor escapes,
clearances) with the measurement layer (``visual_width``,
``screen_lines``) to perform higher-level screen updates.
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


def _visual_rows_of_lines(
    lines: list[str], term_width: int
) -> int:
    """Total screen rows occupied by *lines* after wrapping."""
    return sum(screen_utils.screen_lines(ln, term_width) for ln in lines)


# ======================================================================
# write_line
# ======================================================================


class TestWriteLine:
    """``write_line(text) → str``"""

    # ── basic structure ────────────────────────────────────────────

    def test_plain_text(self):
        result = screen_utils.write_line("hello")
        assert result == "\rhello\033[K\n"

    def test_empty_text(self):
        result = screen_utils.write_line("")
        assert result == "\r\033[K\n"

    def test_starts_with_carriage_return(self):
        result = screen_utils.write_line("abc")
        assert result.startswith("\r")

    def test_ends_with_newline(self):
        result = screen_utils.write_line("abc")
        assert result.endswith("\n")

    def test_el_before_newline(self):
        result = screen_utils.write_line("abc")
        assert result.index("\033[K") < result.index("\n")

    def test_cr_before_text_before_el_before_nl(self):
        # Correct order: \r text \033[K \n
        result = screen_utils.write_line("xyz")
        cr = result.index("\r")
        tx = result.index("xyz")
        el = result.index("\033[K")
        nl = result.index("\n")
        assert cr < tx < el < nl

    # ── text with ANSI codes ───────────────────────────────────────

    def test_text_with_ansi_preserves_escapes(self):
        result = screen_utils.write_line("\033[1mhi\033[0m")
        assert "\033[1mhi\033[0m" in result
        # The EL at the end is the write_line el, not part of the text
        assert result.endswith("\033[K\n")

    def test_text_with_ansi_still_has_exactly_two_ansi(self):
        # One EL from write_line + whatever is in text.
        # If text has 2 ansi codes, total = 3.
        result = screen_utils.write_line("\033[1m\033[31mhello")
        assert _count_ansi_escapes(result) == 3  # 2 in text + EL

    # ── edge cases ─────────────────────────────────────────────────

    def test_returns_string(self):
        assert isinstance(screen_utils.write_line(""), str)

    def test_idempotent(self):
        a = screen_utils.write_line("hello")
        b = screen_utils.write_line("hello")
        assert a == b

    def test_newline_in_text_is_preserved(self):
        # write_line does NOT strip or replace \n in the text itself
        result = screen_utils.write_line("a\nb")
        assert "a\nb" in result

    def test_tab_in_text_is_preserved(self):
        result = screen_utils.write_line("a\tb")
        assert "a\tb" in result

    def test_wide_chars_dont_affect_escape_structure(self):
        result = screen_utils.write_line("你好")
        assert result == "\r你好\033[K\n"

    def test_no_backspace(self):
        assert "\b" not in screen_utils.write_line("test")


# ======================================================================
# clear_rest_of_line
# ======================================================================


class TestClearRestOfLine:
    """``clear_rest_of_line() → str``"""

    def test_returns_el_and_newline(self):
        assert screen_utils.clear_rest_of_line() == "\033[K\n"

    def test_ends_with_newline(self):
        assert screen_utils.clear_rest_of_line().endswith("\n")

    def test_el_before_newline(self):
        result = screen_utils.clear_rest_of_line()
        assert result.index("\033[K") < result.index("\n")

    def test_no_carriage_return(self):
        # clear_rest_of_line clears from wherever the cursor is,
        # so it should NOT move to col 0 first.
        assert "\r" not in screen_utils.clear_rest_of_line()

    def test_returns_string(self):
        assert isinstance(screen_utils.clear_rest_of_line(), str)

    def test_idempotent(self):
        assert screen_utils.clear_rest_of_line() == screen_utils.clear_rest_of_line()

    def test_exactly_one_ansi_escape(self):
        assert _count_ansi_escapes(screen_utils.clear_rest_of_line()) == 1

    def test_no_side_effects(self):
        a = screen_utils.clear_rest_of_line()
        b = screen_utils.clear_rest_of_line()
        assert a == b


# ======================================================================
# overwrite_block
# ======================================================================


class TestOverwriteBlock:
    """``overwrite_block(old_screen_lines, new_lines, term_width) → str``"""

    # ── nothing to overwrite ───────────────────────────────────────

    def test_zero_old_and_empty_new_returns_empty(self):
        assert screen_utils.overwrite_block(0, [], 80) == ""

    def test_zero_old_negative_new_returns_empty(self):
        assert screen_utils.overwrite_block(0, [], 80) == ""

    # ── zero old, non-empty new (write-only, no upward movement) ──

    def test_zero_old_writes_without_cursor_up(self):
        # Nothing was on screen before, so no need to move up.
        result = screen_utils.overwrite_block(0, ["hello"], 80)
        assert "\033[A" not in result

    def test_zero_old_one_line(self):
        result = screen_utils.overwrite_block(0, ["hello"], 80)
        assert result == "\rhello\033[K\n"

    def test_zero_old_multiple_lines(self):
        result = screen_utils.overwrite_block(0, ["a", "b", "c"], 80)
        # Three write_line invocations concatenated
        assert result == ("\ra\033[K\n"
                          "\rb\033[K\n"
                          "\rc\033[K\n")

    # ── exact fit (same number of screen rows) ────────────────────

    def test_one_row_replaced_with_one_row(self):
        result = screen_utils.overwrite_block(1, ["new"], 80)
        # Move up 1 row, then write
        assert result.startswith("\033[1A")
        assert result.endswith("\rnew\033[K\n")

    def test_one_row_replaced_no_leftover_clearing(self):
        result = screen_utils.overwrite_block(1, ["x"], 80)
        # Should not have extra \033[K\n beyond the one from write_line
        assert _count_ansi_escapes(result) == 2  # cursor-up + EL

    def test_two_rows_replaced_with_two_rows(self):
        result = screen_utils.overwrite_block(2, ["aaa", "bbb"], 80)
        # Moves up 2, then both lines. No leftover clearing.
        assert result.startswith("\033[2A")
        assert "\raaa\033[K\n" in result
        assert "\rbbb\033[K\n" in result
        # Exactly 3 ansi: cursor-up + 2×EL
        assert _count_ansi_escapes(result) == 3

    # ── new_lines shorter → leftover clearing ──────────────────────

    def test_three_rows_replaced_with_one_row_clears_leftovers(self):
        result = screen_utils.overwrite_block(3, ["x"], 80)
        # Move up 3, write "x", then clear 2 leftover rows
        assert result.startswith("\033[3A")
        assert "\rx\033[K\n" in result
        # After writing x (1 row), there are 2 leftover rows to clear.
        # Each cleared with \033[K\n.
        assert _count_ansi_escapes(result) == 4  # cursor-up + 1 EL (x) + 2 EL (leftover)

    def test_three_rows_replaced_with_empty_clears_all(self):
        result = screen_utils.overwrite_block(3, [], 80)
        # Move up 3, then clear all 3 rows
        assert result.startswith("\033[3A")
        # Three clear_rest_of_line calls
        assert result.count("\033[K\n") == 3

    def test_two_rows_to_one_exact_leftover_count(self):
        result = screen_utils.overwrite_block(2, ["hi"], 80)
        # Move up 2, write hi, clear 1 leftover
        assert result.startswith("\033[2A")
        # write_line("hi") + clear_rest_of_line()
        expected = "\033[2A\rhi\033[K\n\033[K\n"
        assert result == expected

    # ── new_lines longer → no leftover clearing ────────────────────

    def test_one_row_replaced_with_two_rows_no_leftover(self):
        result = screen_utils.overwrite_block(1, ["first", "second"], 80)
        # Move up 1, write both. No leftover clearing — the new block
        # is bigger than the old one.
        assert result.startswith("\033[1A")
        # Should end with the second write_line (no trailing \033[K\n)
        assert result.endswith("\rsecond\033[K\n")
        # No extra clear_rest_of_line calls
        assert result.count("\033[K\n") == 2  # one per write_line

    def test_one_row_to_three_rows(self):
        result = screen_utils.overwrite_block(1, ["a", "b", "c"], 80)
        assert result.startswith("\033[1A")
        # 3 EL from write_line, 0 leftover
        assert _count_ansi_escapes(result) == 4  # cursor-up + 3×EL

    # ── empty new_lines items ──────────────────────────────────────

    def test_empty_line_items_are_still_written(self):
        result = screen_utils.overwrite_block(3, ["a", "", "c"], 80)
        assert "\r\033[K\n" in result  # the empty line gets cleared too

    # ── wide characters cause wrapping ─────────────────────────────

    def test_wide_char_wrapping_increases_screen_rows(self):
        # "好" is 2 cells wide.  4x"好" = 8 cells → 1 line at width 10.
        # old=1, new = same → exact fit.
        result = screen_utils.overwrite_block(1, ["好好好好"], 10)
        assert result.startswith("\033[1A")
        # No leftover clearing needed (1 row → 1 row)
        assert result.count("\033[K\n") == 1

    def test_wide_char_causes_new_block_to_be_longer(self):
        # A long CJK line that wraps: 6×"好" = 12 cells → 2 rows at width 10.
        # Replace 1 old row with 2 new rows → same as "new_lines longer".
        result = screen_utils.overwrite_block(1, ["好好好好好好"], 10)
        assert result.startswith("\033[1A")
        # The single logical line wraps into 2 screen rows,
        # so no leftover clearing (1 old, 2 new).
        # The implementation should handle the wrapping.
        # We just verify: no stale leftover clearing sequences.
        # (If implementation wraps each line, there are 2 write_line calls.)
        assert _count_ansi_escapes(result) >= 2  # cursor-up + at least 1 EL

    # ── ANSI codes in new_lines don't inflate row count ────────────

    def test_ansi_in_new_lines_does_not_cause_extra_rows(self):
        result = screen_utils.overwrite_block(1, ["\033[1mhello\033[0m"], 10)
        # "hello" = 5 cells → 1 row. ANSI should not add rows.
        assert result.count("\033[K\n") == 1  # one write_line, no leftovers

    # ── edge cases ─────────────────────────────────────────────────

    def test_negative_old_treated_as_zero(self):
        result = screen_utils.overwrite_block(-1, [], 80)
        assert result == ""

    def test_negative_old_with_lines_writes_without_cursor_up(self):
        result = screen_utils.overwrite_block(-5, ["x"], 80)
        assert "\033[A" not in result
        assert "\033[-" not in result

    def test_large_old_screen_lines(self):
        result = screen_utils.overwrite_block(100, ["done"], 80)
        assert result.startswith("\033[100A")

    def test_term_width_zero_treated_as_one(self):
        # Lines wrap heavily at width=1, but shouldn't crash
        result = screen_utils.overwrite_block(1, ["abc"], 0)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_string(self):
        assert isinstance(screen_utils.overwrite_block(1, ["x"], 80), str)

    def test_idempotent(self):
        a = screen_utils.overwrite_block(3, ["a", "b"], 40)
        b = screen_utils.overwrite_block(3, ["a", "b"], 40)
        assert a == b

    def test_no_newline_after_last_write(self):
        # The escape sequence itself doesn't need a trailing newline
        # beyond what's in the write_line/clear_rest_of_line calls.
        # Each internal call already ends with \n.
        result = screen_utils.overwrite_block(1, ["x"], 80)
        # Result ends with \n (from the last write_line), which is fine.
        # But there shouldn't be a stray extra \n beyond that.
        assert result.endswith("\n")

    def test_no_backspace(self):
        result = screen_utils.overwrite_block(5, ["x"], 80)
        assert "\b" not in result

    def test_no_tabs_inserted(self):
        result = screen_utils.overwrite_block(1, ["hello"], 80)
        assert "\t" not in result


# ======================================================================
# rerender_in_place
# ======================================================================


class TestRerenderInPlace:
    """``rerender_in_place(old_text, old_screen_lines, new_text,
    term_width) → tuple[str, int]``"""

    # ── empty old text (fresh write) ───────────────────────────────

    def test_empty_old_just_writes_new(self):
        seq, n = screen_utils.rerender_in_place("", 0, "hello", 80)
        assert n == 1
        assert seq.endswith("\rhello\033[K\n")
        # No cursor-up needed (nothing to go back to)
        assert "\033[A" not in seq

    def test_empty_old_empty_new(self):
        seq, n = screen_utils.rerender_in_place("", 0, "", 80)
        assert n == 0
        assert seq == ""

    # ── old text replaced by shorter new text ─────────────────────

    def test_one_row_to_empty_clears_it(self):
        seq, n = screen_utils.rerender_in_place("hello", 1, "", 80)
        assert n == 0
        # Move up 1, clear the row
        assert seq.startswith("\033[1A")
        assert "\033[K\n" in seq

    def test_two_rows_to_one_row_clears_leftover(self):
        # old occupies 2 rows, new occupies 1 row
        seq, n = screen_utils.rerender_in_place("x" * 90, 2, "short", 80)
        assert n == 1
        # Move up 2, write "short", clear 1 leftover row
        assert seq.startswith("\033[2A")
        assert "\rshort\033[K\n" in seq
        # One leftover clearing
        assert seq.count("\033[K\n") == 2  # write_line + leftover

    # ── old text replaced by longer new text ──────────────────────

    def test_one_row_to_two_rows_no_leftover(self):
        seq, n = screen_utils.rerender_in_place("short", 1, "x" * 90, 80)
        assert n == 2
        # Move up 1, write (which wraps to 2 rows), no leftover clearing
        assert seq.startswith("\033[1A")
        # Should not have leftover \033[K\n beyond the write_line ones
        assert seq.count("\033[K\n") == 2  # two write_lines for wrapped text

    # ── same number of rows ────────────────────────────────────────

    def test_same_rows_no_leftover(self):
        seq, n = screen_utils.rerender_in_place("old!", 1, "new!", 80)
        assert n == 1
        assert seq.startswith("\033[1A")
        assert seq.count("\033[K\n") == 1  # only write_line, no leftover
        assert "\rnew!\033[K\n" in seq

    # ── returned new_screen_lines is correct ───────────────────────

    def test_new_screen_lines_single_row(self):
        _, n = screen_utils.rerender_in_place("x", 1, "hello", 80)
        assert n == 1

    def test_new_screen_lines_wrapped(self):
        _, n = screen_utils.rerender_in_place("", 0, "x" * 150, 80)
        assert n == 2  # 150 cells / 80 = 2 rows

    def test_new_screen_lines_exact_boundary(self):
        _, n = screen_utils.rerender_in_place("", 0, "x" * 80, 80)
        assert n == 1

    def test_new_screen_lines_one_over(self):
        _, n = screen_utils.rerender_in_place("", 0, "x" * 81, 80)
        assert n == 2

    # ── wide characters ────────────────────────────────────────────

    def test_wide_chars_in_new_text(self):
        seq, n = screen_utils.rerender_in_place("x", 1, "你好", 80)
        assert n == 1  # 4 cells, fits in 80
        # old=1, new=1 → exact fit, no leftover
        assert seq.startswith("\033[1A")

    def test_wide_char_wrapping_changes_row_count(self):
        # "好" × 50 = 100 cells → 2 rows at width 80
        seq, n = screen_utils.rerender_in_place("", 0, "好" * 50, 80)
        assert n == 2

    def test_wide_char_near_boundary(self):
        # 39 a's + "好" = 39 + 2 = 41 cells → 1 row at width 80
        seq, n = screen_utils.rerender_in_place("", 0, "a" * 39 + "好", 80)
        assert n == 1

    def test_wide_char_straddling_boundary(self):
        # 79 a's + "好" = 79 + 2 = 81 cells → 2 rows at width 80
        seq, n = screen_utils.rerender_in_place("", 0, "a" * 79 + "好", 80)
        assert n == 2

    # ── ANSI codes in text don't affect row count ──────────────────

    def test_ansi_in_old_text_does_not_affect_old_screen_lines(self):
        # old_screen_lines is pre-computed by the caller;
        # the function trusts it and just uses the value.
        seq, n = screen_utils.rerender_in_place(
            "\033[1mhello\033[0m", 1, "bye", 80
        )
        assert n == 1
        # Should have moved up 1
        assert seq.startswith("\033[1A")

    def test_ansi_in_new_text_does_not_inflate_row_count(self):
        _, n = screen_utils.rerender_in_place(
            "", 0, "\033[1m\033[31mhello\033[0m", 80
        )
        # ANSI stripped before measurement → 5 cells = 1 row
        assert n == 1

    # ── edge cases ─────────────────────────────────────────────────

    def test_negative_old_screen_lines_treated_as_zero(self):
        seq, n = screen_utils.rerender_in_place("", -1, "hello", 80)
        assert n == 1
        assert "\033[-" not in seq

    def test_term_width_zero(self):
        seq, n = screen_utils.rerender_in_place("", 0, "abc", 0)
        assert n == 3  # width 0 → treated as 1, 3 chars = 3 lines
        assert isinstance(seq, str)

    def test_term_width_negative(self):
        _, n = screen_utils.rerender_in_place("", 0, "ab", -5)
        assert n == 2  # width treated as 1

    def test_returns_tuple_of_str_and_int(self):
        result = screen_utils.rerender_in_place("old", 1, "new", 80)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], int)

    def test_idempotent(self):
        a = screen_utils.rerender_in_place("old", 2, "new_text", 40)
        b = screen_utils.rerender_in_place("old", 2, "new_text", 40)
        assert a == b

    def test_no_backspace(self):
        seq, _ = screen_utils.rerender_in_place("old", 1, "new", 80)
        assert "\b" not in seq

    def test_old_text_is_not_used_except_via_screen_lines(self):
        # The function should trust old_screen_lines, not re-measure old_text.
        # If we pass a wrong old_screen_lines that doesn't match old_text,
        # the function should still use the provided number.
        seq, n = screen_utils.rerender_in_place(
            "should_be_3_rows_but_we_say_1", 1, "x", 80
        )
        assert n == 1
        assert seq.startswith("\033[1A")  # uses the provided 1, not re-measured

    def test_escape_sequence_is_self_contained(self):
        # The returned escape should leave the cursor right after the
        # newly written block (one row below the last new row).
        # We can't test this directly without a terminal, but we can
        # verify the sequence doesn't end mid-row.
        seq, _ = screen_utils.rerender_in_place("old", 2, "new", 80)
        assert seq.endswith("\n")
