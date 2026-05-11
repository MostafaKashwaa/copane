"""
Pluggable renderers for streaming LLM responses.

Usage::

    from copane.renderers import get_renderer

    renderer = get_renderer("regex")   # or "raw", "markdown_it", "rich_buffer", "raw_replace"
    await print_streamed_response(stream, renderer=renderer)

The renderer is selected via the ``COPANE_RENDERER`` environment variable.
If unset, ``regex`` is used (lightweight ANSI formatting on-the-fly).
"""

from __future__ import annotations

import os

from copane.renderers._base import Renderer
from copane.renderers.raw_renderer import RawRenderer
from copane.renderers.regex_renderer import RegexRenderer
from copane.renderers.raw_replace_renderer import RawReplaceRenderer

# Optional-dependency renderers — imported lazily by get_renderer()
# to avoid ImportError when the optional packages are missing.

__all__ = [
    "Renderer",
    "RawRenderer",
    "RegexRenderer",
    "RawReplaceRenderer",
    "MarkdownItRenderer",
    "RichBufferRenderer",
    "get_renderer",
    "get_renderer_key",
    "AVAILABLE_RENDERERS",
]

AVAILABLE_RENDERERS: dict[str, str] = {
    "raw": "RawRenderer — no markdown (passthrough)",
    "regex": "RegexRenderer — inline **bold**, *italic*, `code`",
    "raw_replace": "RawReplaceRenderer — stream raw, replace spans in-place",
    "markdown_it": "MarkdownItRenderer — streaming tokenizer (needs markdown-it-py)",
    "rich_buffer": "RichBufferRenderer — raw-then-replace via rich (needs rich)",
}

# Reverse mapping: class name → key
_CLASS_TO_KEY: dict[str, str] = {
    "RawRenderer": "raw",
    "RegexRenderer": "regex",
    "RawReplaceRenderer": "raw_replace",
    "MarkdownItRenderer": "markdown_it",
    "RichBufferRenderer": "rich_buffer",
}


def get_renderer(name: str | None = None) -> Renderer:
    """Create a renderer by name.

    If *name* is ``None``, reads the ``COPANE_RENDERER`` env var
    (default: ``"regex"``).

    Raises ``ValueError`` for unknown names and ``ImportError`` when
    an optional dependency is missing.
    """
    if name is None:
        name = os.environ.get("COPANE_RENDERER", "regex").strip().lower()

    match name:
        case "raw":
            return RawRenderer()
        case "regex":
            return RegexRenderer()
        case "raw_replace":
            return RawReplaceRenderer()
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


def get_renderer_key(renderer: Renderer | None) -> str:
    """Return the config key for a renderer instance (e.g. ``"regex"``).

    Returns ``"?"`` if the renderer is ``None`` or its class is unknown.
    """
    if renderer is None:
        return "?"
    return _CLASS_TO_KEY.get(type(renderer).__name__, "?")
