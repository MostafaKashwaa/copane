"""Lightweight file logger for copane — writes to ``~/.copane/copane.log``.

Use this instead of ``print()`` when debugging state transitions so that
the terminal UI (streaming, renderer cursor tracking) isn't disturbed.

Usage::

    from copane.log import log

    log("title generated: %s", title)
    log("title generation FAILED: %s", e)
"""

import os
import time
import threading
from pathlib import Path


def _log_path() -> Path:
    return Path.home() / ".copane" / "copane.log"


_lock = threading.Lock()


def log(fmt: str, *args) -> None:
    """Append a timestamped line to the copane log file.

    Thread-safe.  Never raises — failures are silently ignored so that
    logging bugs can't break the agent.
    """
    try:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        line = (ts + "  " + (fmt % args if args else fmt)).rstrip() + "\n"
        with _lock:
            with open(_log_path(), "a") as f:
                f.write(line)
    except Exception:
        pass
