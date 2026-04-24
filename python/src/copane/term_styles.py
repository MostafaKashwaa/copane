# ANSI color codes for 256-color terminals

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
BRACKET_LEFT  = "╭"
BRACKET_RIGHT = "╰"
CORNER_TL     = "┌"
CORNER_TR     = "┐"
CORNER_BL     = "└"
CORNER_BR     = "┘"

# Small glyphs for status indicators
BULLET      = "•"
ARROW_RIGHT = "→"
ARROW_LEFT  = "←"
CHECKMARK   = "✓"
CROSS       = "✗"
WARN        = "⚠"
INFO_GLYPH  = "ℹ"
STAR        = "✦"
LIGHTNING   = "⚡"

# ════════════════════════════════════════════════════════════════════════
#  PRINTING HELPERS
# ════════════════════════════════════════════════════════════════════════


def print_section_header(title, color=Colors.PRIMARY):
    """Print a section header with style."""
    print(f"\n{color}{Colors.BOLD}{SEPARATOR}{Colors.RESET}")
    print(f"{color}{Colors.BOLD} {title}{Colors.RESET}")
    print(f"{color}{Colors.BOLD}{SEPARATOR}{Colors.RESET}")


def print_success(message):
    """Print a success message."""
    print(f"{Colors.SUCCESS}{CHECKMARK} {message}{Colors.RESET}")


def print_warning(message):
    """Print a warning message."""
    print(f"{Colors.WARNING}{WARN} {message}{Colors.RESET}")


def print_error(message):
    """Print an error message."""
    print(f"{Colors.ERROR}{CROSS} {message}{Colors.RESET}")


def print_info(message):
    """Print an info message."""
    print(f"{Colors.INFO}{INFO_GLYPH} {message}{Colors.RESET}")


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
