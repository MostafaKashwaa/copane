"""
RegexRenderer — lightweight streaming renderer that converts basic
markdown patterns to ANSI codes on the fly.

Handles ``**bold**``, ``*italic*``, ``` ``code`` ```, and ``### headings``.
Falls back to raw text for anything else.  Zero extra dependencies.
"""

import re

from copane.renderers._base import Renderer
from copane.term_styles import Colors, get_dim

_THINKING_HEADER = f"{Colors.INFO}Thinking{Colors.RESET}"

# ── Inline patterns (streaming-safe — applied per chunk) ──────────────

_BOLD_PAT = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_PAT = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")
_CODE_PAT = re.compile(r"`([^`\n]+?)`")

_BOLD_START = f"{Colors.BOLD}"
_BOLD_END = f"{Colors.RESET}"
_ITALIC_START = f"{Colors.ITALIC}"
_ITALIC_END = f"{Colors.RESET}"
_CODE_START = f"{Colors.BG_DARK}{Colors.INFO}"
_CODE_END = f"{Colors.RESET}"


def _apply_inline(text: str) -> str:
    """Convert inline markdown patterns to ANSI.  Streaming-safe."""
    text = _BOLD_PAT.sub(rf"{_BOLD_START}\1{_BOLD_END}", text)
    text = _ITALIC_PAT.sub(rf"{_ITALIC_START}\1{_ITALIC_END}", text)
    text = _CODE_PAT.sub(rf"{_CODE_START}\1{_CODE_END}", text)
    return text


class RegexRenderer(Renderer):
    """Applies inline markdown regex per chunk.  No block-level parsing."""

    def on_response_begin(self) -> None:
        print(f"\n{_THINKING_HEADER}", end="\n", flush=True)

    def on_response_complete(self) -> None:
        print(flush=True)

    def on_thinking_chunk(self, chunk: str) -> None:
        print(get_dim(chunk), end="", flush=True)

    def on_text_chunk(self, chunk: str) -> None:
        print(_apply_inline(chunk), end="", flush=True)
