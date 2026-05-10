"""
MarkdownItRenderer — streaming markdown renderer powered by markdown-it-py.

Chunks are buffered.  On each chunk the buffer is re-parsed and any
*stable* blocks (paragraphs closed by a double-newline, or completed
code fences) are converted to ANSI and flushed.  The last potentially-
incomplete block stays in the buffer until it stabilises.

Depends on ``markdown-it-py`` (the same parser that powers rich).
"""

from __future__ import annotations

import re
import sys
from typing import List

from copane.renderers._base import Renderer
from copane.term_styles import Colors, get_dim

# Lazy import — markdown-it-py is an optional dependency
try:
    from markdown_it import MarkdownIt
    from markdown_it.token import Token
    HAS_MARKDOWN_IT = True
except ImportError:
    MarkdownIt = None  # type: ignore
    Token = None
    HAS_MARKDOWN_IT = False

_THINKING_HEADER = f"{Colors.INFO}Thinking{Colors.RESET}"

# ── Regex helpers for stability detection ──────────────────────────────

_FENCE_RE = re.compile(r"(?:^|\n)```", re.MULTILINE)


def _is_inside_fence(text: str) -> bool:
    """Return True if *text* contains an odd number of code fences."""
    return len(_FENCE_RE.findall(text)) % 2 == 1


# ── ANSI token renderer ────────────────────────────────────────────────

_H1 = f"{Colors.BOLD}{Colors.PRIMARY}"
_H2 = f"{Colors.BOLD}{Colors.SECONDARY}"
_H3 = f"{Colors.BOLD}{Colors.ACCENT}"
_H4 = f"{Colors.BOLD}{Colors.INFO}"
_HX = f"{Colors.BOLD}"
_CODE_BG = f"{Colors.BG_DARK}{Colors.DIM}"
_LINK = f"{Colors.UNDERLINE}{Colors.INFO}"
_R = Colors.RESET
_B = Colors.BOLD
_I = Colors.ITALIC


def _render_tokens(tokens: List[Token]) -> str:
    """Walk a markdown-it token list and produce ANSI-formatted text."""
    buf: list[str] = []
    _render_token_list(tokens, buf)
    return "".join(buf)


def _render_token_list(tokens: List[Token], buf: list[str]) -> None:
    for token in tokens:
        _render_one(token, buf)


def _render_one(token: Token, buf: list[str]) -> None:
    kind = token.type

    if kind == "inline":
        if token.children:
            _render_token_list(token.children, buf)
        else:
            buf.append(token.content)
        return

    # ── Block tokens ────────────────────────────────────────────────
    if kind == "heading_open":
        tag = token.tag  # "h1", "h2", ...
        prefix = {"h1": _H1, "h2": _H2, "h3": _H3, "h4": _H4}.get(tag, _HX)
        buf.append(f"\n{prefix}")
        return
    if kind == "heading_close":
        buf.append(f"{_R}\n")
        return

    if kind in ("paragraph_open", "paragraph_close",
               "bullet_list_open", "bullet_list_close",
               "ordered_list_open", "ordered_list_close",
               "blockquote_open", "blockquote_close",
               "table_open", "table_close", "thead_open", "thead_close",
               "tbody_open", "tbody_close", "tr_open", "tr_close",
               "th_open", "th_close", "td_open", "td_close"):
        # Structural tokens — rendered by their children / separators
        return

    if kind == "list_item_open":
        buf.append("  • ")
        return
    if kind == "list_item_close":
        buf.append("\n")
        return

    if kind in ("fence", "code_block"):
        buf.append(f"\n{_CODE_BG}{token.content}{_R}\n")
        return

    if kind == "hr":
        buf.append(f"\n{Colors.DIM}───{_R}\n")
        return

    # ── Inline tokens (children of "inline") ────────────────────────
    if kind == "strong_open":
        buf.append(_B)
        return
    if kind == "strong_close":
        buf.append(_R)
        return
    if kind == "em_open":
        buf.append(_I)
        return
    if kind == "em_close":
        buf.append(_R)
        return
    if kind == "code_inline":
        buf.append(f"{_CODE_BG}{token.content}{_R}")
        return
    if kind == "link_open":
        buf.append(_LINK)
        return
    if kind == "link_close":
        buf.append(_R)
        return
    if kind == "text":
        buf.append(token.content)
        return
    if kind in ("softbreak", "hardbreak"):
        buf.append("\n")
        return
    if kind == "s":
        buf.append(f"{Colors.DIM}~~{token.content}~~{_R}")
        return

    # Fallback: any unhandled token type
    buf.append(token.content)


# ── Renderer ───────────────────────────────────────────────────────────

class MarkdownItRenderer(Renderer):
    """Streaming markdown renderer using markdown-it-py's parser.

    Text is buffered until a stable boundary is found (double newline
    or closed code fence), at which point the stable portion is parsed
    and rendered to ANSI.  The last incomplete block remains in the
    buffer for the next chunk.

    If markdown-it-py is not installed, falls back to raw text.
    """

    def __init__(self) -> None:
        if HAS_MARKDOWN_IT:
            self._md = MarkdownIt("commonmark", {"highlight": None})
        else:
            self._md = None
        self._buffer = ""
        self._rendered_len = 0

    # ── Lifecycle ───────────────────────────────────────────────────

    def on_response_begin(self) -> None:
        self._buffer = ""
        self._rendered_len = 0
        if not HAS_MARKDOWN_IT:
            print(
                f"\n{Colors.WARNING}[markdown-it-py not installed — "
                f"falling back to raw output]{Colors.RESET}\n",
                flush=True,
            )
        print(f"\n{_THINKING_HEADER}", end="\n", flush=True)

    def on_response_complete(self) -> None:
        # Flush any remaining buffer
        if self._buffer and self._rendered_len < len(self._buffer):
            remaining = self._buffer[self._rendered_len:]
            print(self._render(remaining), end="", flush=True)
        self._buffer = ""
        self._rendered_len = 0
        print(flush=True)

    # ── Chunks ──────────────────────────────────────────────────────

    def on_thinking_chunk(self, chunk: str) -> None:
        print(get_dim(chunk), end="", flush=True)

    def on_text_chunk(self, chunk: str) -> None:
        self._buffer += chunk
        stable = self._extract_stable()
        if stable:
            print(self._render(stable), end="", flush=True)

    # ── Internals ───────────────────────────────────────────────────

    def _extract_stable(self) -> str:
        """Pull out text that is safe to render now.

        A block is *stable* when we know no more content will be added
        to it: paragraphs end at ``\\n\\n``, code fences at ``\\n```\\n``.
        We keep the last incomplete block in the buffer.
        """
        if not self._md:
            # Fallback: just drain everything
            stable = self._buffer[self._rendered_len:]
            self._rendered_len = len(self._buffer)
            return stable

        # If we're inside an unclosed code fence, nothing new is stable.
        if _is_inside_fence(self._buffer):
            return ""

        # Find the last paragraph break
        boundary = self._buffer.rfind("\n\n")
        if boundary == -1 or boundary < self._rendered_len:
            return ""

        stable = self._buffer[self._rendered_len: boundary + 2]
        self._rendered_len = boundary + 2
        return stable

    def _render(self, text: str) -> str:
        """Parse *text* with markdown-it and produce ANSI output."""
        if not self._md or not text.strip():
            return text
        try:
            tokens = self._md.parse(text)
            return _render_tokens(tokens)
        except Exception:
            return text  # graceful fallback on parse errors
