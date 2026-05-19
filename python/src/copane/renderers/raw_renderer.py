"""
RawRenderer — baseline renderer that prints text exactly as it arrives.

This replicates the current (pre-renderer) behaviour.  No markdown
formatting is applied; chunks are written directly to stdout.
"""

from copane.renderers._base import Renderer
from copane.term_styles import Colors, get_dim

_THINKING_HEADER = f"{Colors.INFO}Thinking{Colors.RESET}"


class RawRenderer(Renderer):
    """Passthrough renderer — current default behaviour."""

    def on_response_begin(self) -> None:
        print(f"\n{_THINKING_HEADER}", end="\n", flush=True)

    def on_response_complete(self) -> None:
        print(flush=True)

    def on_thinking_chunk(self, chunk: str) -> None:
        print(get_dim(chunk), end="", flush=True)

    def on_text_chunk(self, chunk: str) -> None:
        print(chunk, end="", flush=True)

    def on_interrupt(self) -> None:
        ...
