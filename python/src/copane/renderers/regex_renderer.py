"""
RegexRenderer — lightweight streaming renderer that converts basic
markdown patterns to ANSI codes on the fly.

Handles ``**bold**``, ``*italic*``, ``` ``code`` ```, ``~~strikethrough~~``,
``### headings``, fenced code blocks (```` ```lang ````), ``> blockquotes``,
``- / * / +`` unordered lists, ``1.`` ordered lists, ``[text](url)`` links,
and ``---`` / ``***`` / ``___`` horizontal rules.  Zero extra dependencies.

Streaming strategy: each line is buffered until ``\\n``, then processed
as a unit.  This is required because inline patterns (``**bold**``,
`` `code` ``) can span multiple streaming chunks — the opening and
closing delimiters must be seen together for the regex to match.
The per-line delay is negligible (typically <1 s for normal prose).
"""

import re
import shutil

from copane.renderers._base import Renderer
from copane.term_styles import Colors, get_dim

_THINKING_HEADER = f"{Colors.INFO}Thinking{Colors.RESET}"

# ── Inline patterns (applied outside fenced code blocks) ──────────────

_BOLD_PAT = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_PAT = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")
_INLINE_CODE_PAT = re.compile(r"`([^`\n]+?)`")
_STRIKE_PAT = re.compile(r"~~(.+?)~~")
_LINK_PAT = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

_BOLD_START = f"{Colors.BOLD}"
_BOLD_END = f"{Colors.RESET}"
_ITALIC_START = f"{Colors.ITALIC}"
_ITALIC_END = f"{Colors.RESET}"
_INLINE_CODE_START = f"{Colors.BG_DARK}{Colors.INFO}"
_INLINE_CODE_END = f"{Colors.RESET}"
_STRIKE_START = "\033[9m"
_STRIKE_END = f"{Colors.RESET}"
_LINK_TEXT_COLOR = Colors.INFO
_LINK_URL_COLOR = Colors.DIM


def _apply_inline(text: str) -> str:
    """Convert inline markdown patterns to ANSI.  Call only on complete
    lines — patterns that span streaming chunks won't match otherwise."""
    text = _BOLD_PAT.sub(rf"{_BOLD_START}\1{_BOLD_END}", text)
    text = _ITALIC_PAT.sub(rf"{_ITALIC_START}\1{_ITALIC_END}", text)
    text = _STRIKE_PAT.sub(rf"{_STRIKE_START}\1{_STRIKE_END}", text)
    text = _INLINE_CODE_PAT.sub(rf"{_INLINE_CODE_START}\1{_INLINE_CODE_END}", text)
    text = _LINK_PAT.sub(
        rf"{_LINK_TEXT_COLOR}\1{Colors.RESET}{_LINK_URL_COLOR}(\2){Colors.RESET}",
        text,
    )
    return text


# ── Heading patterns ──────────────────────────────────────────────────

_HEADING_PAT = re.compile(r"^(#{1,6})\s+(.+)$")

_HEADING_COLORS = [
    Colors.PRIMARY,     # H1 — bright blue
    Colors.SECONDARY,   # H2 — cyan
    Colors.ACCENT,      # H3 — orange
    Colors.INFO,        # H4 — bright cyan
    Colors.SUCCESS,     # H5 — green
    Colors.WARNING,     # H6 — yellow
]


def _style_heading(line: str) -> str:
    """If *line* is a heading, return ANSI-styled text; else empty str."""
    m = _HEADING_PAT.match(line)
    if not m:
        return ""
    hashes, text = m.group(1), m.group(2)
    level = len(hashes) - 1  # 0-based
    color = _HEADING_COLORS[min(level, len(_HEADING_COLORS) - 1)]
    return f"{Colors.BOLD}{color}{text}{Colors.RESET}"


# ── Fenced code blocks ────────────────────────────────────────────────

# Matches opening/closing fences: ``` or ```python, etc.
# Trailing whitespace is allowed because LLMs often emit stray spaces.
_FENCE_PAT = re.compile(r"^```(\S*)\s*$")

_FENCE_DECORATION = f"{Colors.DIM}{Colors.BG_DARK}"
_FENCE_RESET = Colors.RESET
_CODE_LINE_PREFIX = f"{Colors.DIM}│ "
_CODE_LINE_SUFFIX = Colors.RESET


# ── Blockquote, list, and horizontal-rule patterns ────────────────────

_HR_PAT = re.compile(r"^\s*([\-]{3,}|[\*]{3,}|[\_]{3,})\s*$")
_BQ_PAT = re.compile(r"^>\s?(.*)$")
_UL_PAT = re.compile(r"^(\s*)([-*+])\s+(.*)$")
_OL_PAT = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")

# Blockquote: dimmed text behind a coloured bar.
_BQ_BAR = f"{Colors.DIM}{Colors.ACCENT}│{Colors.RESET}{Colors.DIM} "

# List bullets and numbers get a bold accent colour.
_LIST_BULLET_COLOR = Colors.ACCENT
_LIST_NUM_COLOR = Colors.INFO


class RegexRenderer(Renderer):
    """Applies inline markdown regex + heading + fenced code styling.

    Also handles horizontal rules, blockquotes, list items,
    strikethrough, and links.

    Lines are buffered until newline so that regex patterns see
    complete lines.  Headings split across chunks and fences split
    across chunks are correctly detected.
    """

    def __init__(self) -> None:
        self._line_buffer = ""
        self._in_code_block = False

    # ── Lifecycle ──────────────────────────────────────────────────

    def on_response_begin(self) -> None:
        print(f"\n{_THINKING_HEADER}", flush=True)

    def on_response_complete(self) -> None:
        if self._line_buffer:
            print(self._process_line(self._line_buffer), end="", flush=True)
        print(flush=True)

    # ── Chunk handlers ─────────────────────────────────────────────

    def on_thinking_chunk(self, chunk: str) -> None:
        print(get_dim(chunk), end="", flush=True)

    def on_text_chunk(self, chunk: str) -> None:
        self._line_buffer += chunk

        # Emit every complete line.
        while "\n" in self._line_buffer:
            line, self._line_buffer = self._line_buffer.split("\n", 1)
            print(self._process_line(line), end="\n", flush=True)

    # ── Line processing ────────────────────────────────────────────

    def _process_line(self, line: str) -> str:
        """Apply heading, fenced code, blockquote, list, HR, or inline
        formatting to one line."""

        # ── 1. Fenced code block boundary ──
        m = _FENCE_PAT.match(line)
        if m:
            cols = shutil.get_terminal_size().columns
            if not self._in_code_block:
                self._in_code_block = True
                lang = m.group(1) or ""
                label = f" {lang} " if lang else ""
                bar = "─" * max(cols - len(label) - 4, 0)
                return f"{_FENCE_DECORATION}┌──{label}{bar}{_FENCE_RESET}"
            else:
                self._in_code_block = False
                bar = "─" * max(cols - 4, 0)
                return f"{_FENCE_DECORATION}└──{bar}{_FENCE_RESET}"

        # ── 2. Inside code block — literal, no markdown processing ──
        if self._in_code_block:
            return f"{_CODE_LINE_PREFIX}{line}{_CODE_LINE_SUFFIX}"

        # ── 3. Horizontal rule ──
        if _HR_PAT.match(line):
            cols = shutil.get_terminal_size().columns
            return f"{Colors.DIM}{'─' * cols}{Colors.RESET}"

        # ── 4. Blockquote ──
        bq_m = _BQ_PAT.match(line)
        if bq_m:
            return f"{_BQ_BAR}{_apply_inline(bq_m.group(1))}{Colors.RESET}"

        # ── 5. Heading ──
        styled = _style_heading(line)
        if styled:
            return styled

        # ── 6. Unordered list item ──
        ul_m = _UL_PAT.match(line)
        if ul_m:
            indent, bullet, rest = ul_m.groups()
            return (
                f"{indent}"
                f"{_LIST_BULLET_COLOR}{Colors.BOLD}{bullet}{Colors.RESET}"
                f" {_apply_inline(rest)}"
            )

        # ── 7. Ordered list item ──
        ol_m = _OL_PAT.match(line)
        if ol_m:
            indent, num, rest = ol_m.groups()
            return (
                f"{indent}"
                f"{_LIST_NUM_COLOR}{Colors.BOLD}{num}.{Colors.RESET}"
                f" {_apply_inline(rest)}"
            )

        # ── 8. Normal text with inline formatting ──
        return _apply_inline(line)
