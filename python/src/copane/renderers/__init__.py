"""
Pluggable renderers for streaming LLM responses.

Usage::

    from copane.renderers import get_renderer

    renderer = get_renderer("regex")   # or "raw", "markdown_it", "rich_buffer"
    await print_streamed_response(stream, renderer=renderer)

The renderer is selected via the ``COPANE_RENDERER`` environment variable.
If unset, ``raw`` is used (current behaviour, no markdown formatting).
"""

from __future__ import annotations

import os

from copane.renderers._base import Renderer
from copane.renderers.raw_renderer import RawRenderer
from copane.renderers.regex_renderer import RegexRenderer

# Optional-dependency renderers — imported lazily by get_renderer()
# to avoid ImportError when the optional packages are missing.

__all__ = [
    "Renderer",
    "RawRenderer",
    "RegexRenderer",
    "MarkdownItRenderer",
    "RichBufferRenderer",
    "get_renderer",
    "AVAILABLE_RENDERERS",
]

AVAILABLE_RENDERERS: dict[str, str] = {
    "raw": "RawRenderer — no markdown (default)",
    "regex": "RegexRenderer — inline **bold**, *italic*, `code`",
    "markdown_it": "MarkdownItRenderer — streaming tokenizer (needs markdown-it-py)",
    "rich_buffer": "RichBufferRenderer — raw-then-replace via rich (needs rich)",
}


def get_renderer(name: str | None = None) -> Renderer:
    """Create a renderer by name.

    If *name* is ``None``, reads the ``COPANE_RENDERER`` env var
    (default: ``"raw"``).

    Raises ``ValueError`` for unknown names and ``ImportError`` when
    an optional dependency is missing.
    """
    if name is None:
        name = os.environ.get("COPANE_RENDERER", "raw").strip().lower()

    match name:
        case "raw":
            return RawRenderer()
        case "regex":
            return RegexRenderer()
        case "markdown_it":
            from copane.renderers.markdown_it_renderer import MarkdownItRenderer
            return MarkdownItRenderer()
        case "rich_buffer":
            from copane.renderers.rich_buffer_renderer import RichBufferRenderer
            return RichBufferRenderer()
        case _:
            raise ValueError(
                f"Unknown renderer: {name!r}. "
                f"Available: {', '.join(AVAILABLE_RENDERERS)}"
            )
