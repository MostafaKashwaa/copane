"""
Base classes and protocols for pluggable response renderers.

Renderers are responsible for displaying thinking and text chunks
as they stream from the LLM.  Tool calls, tool responses, and tool
approval stay in ``ui.py`` — they are not markdown-formatted and
do not vary between renderers.
"""

from abc import ABC, abstractmethod


class Renderer(ABC):
    """Pluggable renderer for streaming LLM responses.

    Each renderer receives thinking and text chunks as they arrive
    and decides how to format them for the terminal.
    """

    # ── Lifecycle ──────────────────────────────────────────────────

    @abstractmethod
    def on_response_begin(self) -> None:
        """Called once, just before the first chunk arrives."""
        ...

    @abstractmethod
    def on_response_complete(self) -> None:
        """Called once after the final chunk has been delivered."""
        ...

    # ── Streaming chunks ───────────────────────────────────────────

    @abstractmethod
    def on_thinking_chunk(self, chunk: str) -> None:
        """A chunk of reasoning / thinking text (e.g. chain-of-thought)."""
        ...

    @abstractmethod
    def on_text_chunk(self, chunk: str) -> None:
        """A chunk of the main response text (may contain markdown)."""
        ...

    @abstractmethod
    def on_tool_call_chunk(self, chunk: str) -> None:
        """A chunk of text representing a tool call (e.g. ``[tool]search("query")``)."""
        ...

    @abstractmethod
    def on_tool_response_chunk(self, chunk: str) -> None:
        """A chunk of text representing a tool response (e.g. ``[tool_response]{"result": "value"}``)."""
        ...

    @abstractmethod
    def on_interrupt(self) -> None:
        """Called before out-of-band text (e.g. tool calls) is printed to the terminal.
        The renderer should finalize any trailing incomplete thinking or text chunks, so that the out-of-band text appears in a clean state."""
        ...
