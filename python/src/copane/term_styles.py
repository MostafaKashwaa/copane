# ANSI color codes for 256-color terminals

from prompt_toolkit import ANSI


class Colors:
    # Primary colors
    PRIMARY = "\033[38;5;39m"      # Bright blue
    SECONDARY = "\033[38;5;45m"    # Cyan
    ACCENT = "\033[38;5;208m"      # Orange
    SUCCESS = "\033[38;5;46m"      # Bright green
    WARNING = "\033[38;5;226m"     # Yellow
    ERROR = "\033[38;5;196m"       # Bright red
    INFO = "\033[38;5;51m"         # Bright cyan

    # Backgrounds
    BG_PRIMARY = "\033[48;5;39m"
    BG_SECONDARY = "\033[48;5;45m"
    BG_ACCENT = "\033[48;5;208m"
    BG_DARK = "\033[48;5;235m"

    # Text styles
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"
    BLINK = "\033[5m"
    REVERSE = "\033[7m"

    # Reset
    RESET = "\033[0m"
    CLEAR_LINE = "\033[2K\r"

# =============================================================================
# PROFESSIONAL ASCII LOGO — "copane" (Co-pilot + Pane)
# Three styles: choose by uncommenting your favorite, or keep all three
# =============================================================================


# ── Style 1: Modern / Minimalist ────────────────────────────────────────
# Clean, wide box with bold lettering. Great for 256-color terminals.
LOGO_BOXED = r"""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║         ██████╗ ██████╗ ██████╗  █████╗ ███╗   ██╗███████╗   ║
║        ██╔════╝██╔═══██╗██╔══██╗██╔══██╗████╗  ██║██╔════╝   ║
║        ██║     ██║   ██║██████╔╝███████║██╔██╗ ██║█████╗     ║
║        ██║     ██║   ██║██╔═══╝ ██╔══██║██║╚██╗██║██╔══╝     ║
║        ╚██████╗╚██████╔╝██║     ██║  ██║██║ ╚████║███████╗   ║
║         ╚═════╝ ╚═════╝ ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝   ║
║                                                              ║
║                 ✦  AI Coding Assistant  ✦                    ║
╚══════════════════════════════════════════════════════════════╝"""

# ── Style 2: Retro / Chunky ────────────────────────────────────────────
# Bold, thick characters. Good for smaller terminals or a nostalgic feel.
LOGO_CHUNKY = r"""
   ██████╗ ██████╗ ██████╗  █████╗ ███╗   ██╗███████╗
  ██╔════╝██╔═══██╗██╔══██╗██╔══██╗████╗  ██║██╔════╝
  ██║     ██║   ██║██████╔╝███████║██╔██╗ ██║█████╗
  ██║     ██║   ██║██╔═══╝ ██╔══██║██║╚██╗██║██╔══╝
  ╚██████╗╚██████╔╝██║     ██║  ██║██║ ╚████║███████╗
   ╚═════╝ ╚═════╝ ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝
     ⚡  c o · p a n e  —  A I  C o d i n g  A i d  ⚡"""

# ── Style 3: Tagline Card (compact) ───────────────────────────────────
# Small footprint. Fits in a narrow pane or a status header.
LOGO_COMPACT = r"""
 ╭─────────────────────────────────────╮
 │  ██████╗ ██████╗ ██████╗  █████╗    │
 │ ██╔════╝██╔═══██╗██╔══██╗██╔══██╗   │
 │ ██║     ██║   ██║██████╔╝███████║   │
 │ ██║     ██║   ██║██╔═══╝ ██╔══██║   │
 │ ╚██████╗╚██████╔╝██║     ██║  ██║   │
 │  ╚═════╝ ╚═════╝ ╚═╝     ╚═╝  ╚═╝   │
 │          AI · Code · Tmux           │
 ╰─────────────────────────────────────╯"""

# ── Style 4: Side-by-side ─────────────────────────────────────────────
# Logo + branding on one line, tagline on the next. Clean for wide terms.
LOGO_WIDE = r"""
   ██████╗ ██████╗ ██████╗  █████╗ ███╗   ██╗███████╗   —   AI Coding Agent
  ██╔════╝██╔═══██╗██╔══██╗██╔══██╗████╗  ██║██╔════╝
  ██║     ██║   ██║██████╔╝███████║██╔██╗ ██║█████╗     ✦  Terminal-First
  ██║     ██║   ██║██╔═══╝ ██╔══██║██║╚██╗██║██╔══╝        Multi-Model
  ╚██████╗╚██████╔╝██║     ██║  ██║██║ ╚████║███████╗   ✦  Vim + Tmux
   ╚═════╝ ╚═════╝ ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝        File-Aware"""

# ── Style 5: Single-line banner ───────────────────────────────────────
# For minimalists — a single line that doubles as a status indicator.
LOGO_ONELINER = "  ▷  copane  ◁   AI Coding Agent  •  Vim + Tmux  •  Multi-Model"

# ════════════════════════════════════════════════════════════════════════
#  DEFAULT LOGO — set to your favorite style above
# ════════════════════════════════════════════════════════════════════════
LOGO = LOGO_BOXED

# ════════════════════════════════════════════════════════════════════════
#  EXTRA DECORATIONS & BORDERS
# ════════════════════════════════════════════════════════════════════════

# Separator line spanning the full width
SEPARATOR = "─" * 70
DOUBLE_SEPARATOR = "═" * 70

# Decorative brackets used in status lines and headers
BRACKET_LEFT = "╭"
BRACKET_RIGHT = "╰"
CORNER_TL = "┌"
CORNER_TR = "┐"
CORNER_BL = "└"
CORNER_BR = "┘"

# Small glyphs for status indicators
BULLET = "•"
ARROW_RIGHT = "→"
ARROW_LEFT = "←"
CHECKMARK = "✓"
CROSS = "✗"
WARN = "⚠"
INFO_GLYPH = "ℹ"
STAR = "✦"
LIGHTNING = "⚡"

# ════════════════════════════════════════════════════════════════════════
#  PRINTING HELPERS
# ════════════════════════════════════════════════════════════════════════


def print_section_header(title, color=Colors.PRIMARY):
    """Print a section header with style."""
    print(f"\n{color}{Colors.BOLD}{SEPARATOR}{Colors.RESET}")
    print(f"{color}{Colors.BOLD} {title}{Colors.RESET}")
    print(f"{color}{Colors.BOLD}{SEPARATOR}{Colors.RESET}")

def get_colored(message, color=Colors.PRIMARY, sign=""):
    """Return a message string wrapped in ANSI color codes."""
    return f"{color}{sign}{message}{Colors.RESET}"


def print_colored(message, color=Colors.PRIMARY, sign=""):
    """Print a message in the specified color."""
    print(get_colored(message, color, sign))


def print_tuble(columns, color1=Colors.PRIMARY, color2=Colors.INFO, spacing="18", left_pad="  "):
    """Print two columns of text side by side, each with its own color."""
    col1, col2 = columns
    print(f"{left_pad}{color1}{col1:<{spacing}}{Colors.RESET} {color2}{col2}{Colors.RESET}")

def get_row(columns, colors=[], column_sizes=[], left_pad="  ", decorations=[]):
    """Return a formatted row string with multiple columns, each with its own color and width."""
    line = left_pad
    for i, col in enumerate(columns):
        color = colors[i] if i < len(colors) else Colors.RESET
        size = column_sizes[i] if i < len(column_sizes) else 20
        decoration = decorations[i] if i < len(decorations) else ''
        line += f"{color}{decoration}{col:<{size}}{Colors.RESET} "
    return line

def print_row(columns, colors=[], column_sizes=[], left_pad="  ", decorations=[]):
    """Print a table with multiple columns, each with its own color and width."""
    print(get_row(columns, colors, column_sizes, left_pad, decorations))

def get_success_message(message, sign=f'{CHECKMARK} '):
    """Return a success message string with ANSI color codes."""
    return f"{Colors.SUCCESS}{sign}{message}{Colors.RESET}"

def print_success(message, sign=f'{CHECKMARK} '):
    """Print a success message."""
    print(get_success_message(message, sign))

def get_warning_message(message, sign=f'{WARN} '):
    """Return a warning message string with ANSI color codes."""
    return f"{Colors.WARNING}{sign}{message}{Colors.RESET}"

def print_warning(message, sign=f'{WARN} '):
    """Print a warning message."""
    print(get_warning_message(message, sign))

def get_error_message(message, sign=f'{CROSS} '):
    """Return an error message string with ANSI color codes."""
    return f"{Colors.ERROR}{sign}{message}{Colors.RESET}"

def print_error(message, sign=f'{CROSS} '):
    """Print an error message."""
    print(get_error_message(message, sign))

def get_info_message(message, sign=f'{INFO_GLYPH} '):
    """Return an info message string with ANSI color codes."""
    return f"{Colors.INFO}{sign}{message}{Colors.RESET}"

def print_info(message, sign=f'{INFO_GLYPH} '):
    """Print an info message."""
    print(get_info_message(message, sign))


def print_dim(message):
    """Print a dimmed message."""
    print(f"{Colors.DIM}{message}{Colors.RESET}")

def get_bold(message, color=''):
    """Return a bold message string with ANSI color codes."""
    return f"{color}{Colors.BOLD}{message}{Colors.RESET}"

def print_bold(message, color=''):
    """Print a bold message in the specified color."""
    print(get_bold(message, color))


def ansi_bold(message, color=Colors.PRIMARY):
    """Print a bold message in the specified color."""
    return ANSI(f"{color}{Colors.BOLD}{message}{Colors.RESET}")


def ansi_warn(message, sign=WARN):
    """Return a warning message with a warning glyph."""
    return ANSI(get_warning_message(message, sign))


# ════════════════════════════════════════════════════════════════════════
#  FANCY DECORATIVE PRINT
# ════════════════════════════════════════════════════════════════════════


def print_box(text, color=Colors.PRIMARY, width=60):
    """Print text inside a decorative box."""
    inner = f" {text} ".center(width - 4)
    print(f"{color}{CORNER_TL}{'─' * (width - 2)}{CORNER_TR}{Colors.RESET}")
    print(f"{color}│{Colors.RESET}{Colors.BOLD}{inner}{color}│{Colors.RESET}")
    print(f"{color}{CORNER_BL}{'─' * (width - 2)}{CORNER_BR}{Colors.RESET}")


def print_status_line(label, value, label_color=Colors.PRIMARY,
                      value_color=Colors.INFO, width=70):
    """Print a labelled status line aligned to a fixed width."""
    padding = width - len(label) - len(str(value)) - 6
    pad = " " * max(padding, 1)
    print(f"  {label_color}{BULLET}{Colors.RESET} "
          f"{label_color}{Colors.BOLD}{label}:{Colors.RESET}"
          f"{pad}"
          f"{value_color}{value}{Colors.RESET}")


def print_color_preview():
    """Print a sample of all theme colors — useful for debugging."""
    print(f"\n{Colors.BOLD}── Color Preview ──{Colors.RESET}")
    for name in ["PRIMARY", "SECONDARY", "ACCENT", "SUCCESS",
                 "WARNING", "ERROR", "INFO"]:
        code = getattr(Colors, name)
        print(f"  {code}{Colors.BOLD}{name:<12}{Colors.RESET}"
              f"  {code}███  {code}▄▄▄  {code}━━━{Colors.RESET}")
    print(f"  {Colors.BOLD}{Colors.REVERSE} REVERSE {Colors.RESET}"
          f"  {Colors.BG_DARK}  DARK BG  {Colors.RESET}")
    print()
