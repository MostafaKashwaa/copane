"""
Base classes and protocols for pluggable response renderers.

Renderers are responsible for displaying thinking and text chunks
as they stream from the LLM.  Tool calls, tool responses, and tool
approval stay in ``ui.py`` — they are not markdown-formatted and
do not vary between renderers.
"""

from abc import ABC, abstractmethod
from inspect import getcomments

from copane.term_styles import Colors, get_colored
from copane.tools._base import ToolResult


class Renderer(ABC):
    tool_lines = {}
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

    def on_tool_call_chunk(self, chunk: str) -> None:
        """A chunk of text representing a tool call (e.g. ``[tool]search("query")``)."""
        tool_name, tool_id = chunk
        self.tool_lines[tool_id] = f"\n{get_colored(f'🔧 [{tool_name}]:  ', Colors.ACCENT)}"

    def on_tool_response_chunk(self, chunk: str) -> None:
        """A chunk of text representing a tool response (e.g. ``[tool_response]{"result": "value"}``)."""
        response, call_id = chunk
        self.tool_lines[call_id] += self._format_tool_output(response)
        print(self.tool_lines[call_id], end="", flush=True)
        print(Colors.RESET, end="", flush=True)


    def on_interrupt(self) -> None:
        """Called before out-of-band text (e.g. tool calls) is printed to the terminal.
        The renderer should finalize any trailing incomplete thinking or text chunks, so that the out-of-band text appears in a clean state."""
        ...


# ── Tool output helpers ────────────────────────────────────────────────

    @staticmethod
    def _format_tool_output(res) -> str:
        """Return a compact one-liner status icon + first-line preview.

        The result always starts with `` ✓`` (success) or `` ✗`` (failure).
        """
        if isinstance(res, str):
            # Legacy support for tools that return raw strings instead of ToolResult
            output = res.strip()
            if output.startswith("[exit code: 0]"):
                line0 = output.splitlines()[0] if output else ""
                return f" ✓ {line0} "
            elif output.startswith("[Error:") or output.startswith("[exit code:"):
                line0 = output.splitlines()[0] if output else ""
                return f" ✗ {line0} "
            elif output.startswith("Wrote "):
                return f" ✓ ({output})"
            elif output:
                line0 = output.splitlines()[0]
                return f" ✓ {line0} "
            else:
                return " ✓ "
        if res.success:
            if res.output.strip():
                line0 = res.output.splitlines()[0]
                return get_colored(f" ✓ {line0} ", Colors.SUCCESS)
            else:
                return get_colored(" ✓ ", Colors.SUCCESS)
        else:
            error_text = res.error.splitlines()[0].strip(
            ) if res.error else res.output.splitlines()[0].strip() if res.output else "Empty output"
            return get_colored(f" ✗ {error_text} ", Colors.ERROR)
