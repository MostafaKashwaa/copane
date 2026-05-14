import re

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


