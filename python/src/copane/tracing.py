"""Conditional LangSmith tracing.  Pass-through unless explicitly enabled.

Users who never configure LangSmith (no ``LANGSMITH_API_KEY``, or
``LANGSMITH_TRACING`` not set to ``true``) incur zero overhead and
zero log noise.  The real ``langsmith`` module is never even imported
in that case.

Offline users who *have* configured tracing are also protected:
LangSmith's own loggers are silenced so transient network errors
don't flood the terminal.  When connectivity returns, the background
thread drains the queue automatically.
"""

import functools
import inspect
import logging
import os

# ── Pre-emptive logger silencing ─────────────────────────────────────
# These fire at import time, before any langsmith code runs, so even
# if tracing is enabled the noisy "Failed to submit trace data" errors
# never reach the user's terminal.
logging.getLogger("langsmith.client").setLevel(logging.CRITICAL)
logging.getLogger("langsmith").setLevel(logging.WARNING)


def _tracing_enabled() -> bool:
    """Return ``True`` only when the user has explicitly opted in."""
    flag = os.environ.get("LANGSMITH_TRACING", "")
    key = os.environ.get("LANGSMITH_API_KEY", "")
    return flag.lower() == "true" and bool(key)


def _pass_through_decorator(func=None, /, **dec_kwargs):
    """Identity decorator that is API-compatible with ``@traceable``.

    Supports all three calling conventions:

    * ``@traceable`` — bare decorator
    * ``@traceable()`` — called with no arguments
    * ``@traceable(name="…", run_type="…")`` — keyword arguments

    Both sync and async functions are handled.
    """
    if func is None:
        # Called as ``@traceable()`` or ``@traceable(kw=…)``
        return _pass_through_decorator

    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*a, **kw):
            return await func(*a, **kw)

        return async_wrapper

    @functools.wraps(func)
    def wrapper(*a, **kw):
        return func(*a, **kw)

    return wrapper


if _tracing_enabled():
    from langsmith import traceable  # noqa: F811
else:
    traceable = _pass_through_decorator  # type: ignore[assignment]
