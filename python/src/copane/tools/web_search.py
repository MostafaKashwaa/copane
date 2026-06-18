"""``web_search`` — search the web using Serper.dev (Google Search API)."""

import os
import re
from typing import Annotated

import httpx
from agents import function_tool
from copane.tracing import traceable
from pydantic import Field

from ._base import ToolResult, _strip_config_from_schema, _truncate

_SERPER_URL = "https://google.serper.dev/search"
_SERPER_TIMEOUT = 15          # seconds — network call
_MAX_SEARCH_OUTPUT = 3_000    # characters (search snippets are short)
_MAX_RESULTS = 10             # hard cap
_DEFAULT_NUM_RESULTS = 5


@function_tool
@traceable(run_type="tool", name="Web Search")
async def web_search(
    query: Annotated[str, Field(
        description=(
            "Search query to send to Google.  Be specific and "
            "include relevant keywords."
        ),
    )],
    num_results: Annotated[int, Field(
        description="Number of results to return (1-10, default 5)"
                    "Use 1-3 for specific lookups (e.g. version numbers, error messages) and 5+ for broader research.",
    )] = _DEFAULT_NUM_RESULTS,
) -> ToolResult:
    """Search the web using Google.

    Returns titles, links, and short snippets for each result.
    Use this to find current documentation, recent solutions,
    library APIs, error messages, or anything beyond your
    knowledge cutoff.  Be specific in your query.
    """
    api_key = os.environ.get("SERPER_API_KEY", "").strip()
    if not api_key:
        return ToolResult(
            success=False,
            error=(
                "SERPER_API_KEY environment variable is not set.  "
                "Get a free key at https://serper.dev and set "
                "SERPER_API_KEY in your environment."
            ),
            error_type="missing_api_key",
        )

    num_results = max(1, min(_MAX_RESULTS, num_results))

    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": num_results}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                _SERPER_URL,
                headers=headers,
                json=payload,
                timeout=_SERPER_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 403:
            detail = "Invalid API key."
        elif status == 429:
            detail = "Rate limited — wait and retry."
        else:
            detail = f"HTTP {status}"
        return ToolResult(
            success=False,
            error=f"Serper search failed: {detail}",
            error_type="api_error",
        )
    except httpx.TimeoutException:
        return ToolResult(
            success=False,
            error="Search timed out.",
            error_type="timeout",
        )
    except Exception as exc:
        return ToolResult(
            success=False,
            error=f"Search failed: {exc}",
            error_type="network_error",
        )

    organic = data.get("organic", [])
    if not organic:
        return ToolResult(
            success=False,
            error="No results found.",
            error_type="no_results",
        )

    # Optional: include search time if Serper reports it
    elapsed = data.get("searchInformation", {}).get("time")
    timing_str = f", {elapsed}s" if elapsed else ""

    lines = [
        f"Results for: {query} ({len(organic)} results{timing_str})",
        "",
    ]

    for item in organic:
        pos = item.get("position", "?")
        title = item.get("title", "(no title)")
        link = item.get("link", "(no link)")
        snippet = item.get("snippet", "").replace("\n", " ")
        lines.append(f"{pos}. {title}")
        lines.append(f"   {link}")
        lines.append(f"   {snippet}")
        lines.append("")

    body = "\n".join(lines)
    body, truncated = _truncate(body, _MAX_SEARCH_OUTPUT, label="output")
    return ToolResult(success=True, output=body, truncated=truncated)


_strip_config_from_schema(web_search.params_json_schema)


# ---------------------------------------------------------------------------
# Summarizer
# ---------------------------------------------------------------------------


def summarize(args: dict, output: str) -> str | None:
    """Produce a one-line summary for conversation compression."""
    query = args.get("query", "?")
    # Count result entries (each starts with a digit followed by ". ")
    count = len(re.findall(r"^\d+\. ", output, re.MULTILINE))
    return f'- web_search "{query}" → {count} results'
