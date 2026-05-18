"""
Session store for copane — manages session files and manifest.

Each logical session (between /clear or app restarts) is stored as a
single JSON file under ``~/.copane/sessions/``. A ``manifest.json``
in the same directory tracks all sessions.

The session file is overwritten after each assistant response (crash
resilience) and on /clear / exit.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any


def _sessions_dir() -> Path:
    """Return (and ensure) the sessions directory."""
    path = Path.home() / ".copane" / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _manifest_path() -> Path:
    return _sessions_dir() / "manifest.json"


def _session_path(session_id: str) -> Path:
    return _sessions_dir() / f"{session_id}.json"


def session_file_path(session_id: str) -> Path:
    """Public accessor for the session file path."""
    return _session_path(session_id)


def generate_session_id() -> str:
    """Generate a unique, human-readable session id.

    Format: ``YYYY-MM-DD_HH-MM-SS-<6-char-hex>``
    """
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    short = uuid.uuid4().hex[:6]
    return f"{ts}-{short}"


# ── Manifest helpers ────────────────────────────────────────────────


def load_manifest() -> list[dict[str, Any]]:
    """Load the session manifest, or return an empty list.

    Sorted by ``last_updated`` descending (most recent first).
    """
    mp = _manifest_path()
    if not mp.exists():
        return []
    try:
        with open(mp) as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        # Sort by last_updated descending
        data.sort(key=lambda e: e.get("last_updated", ""), reverse=True)
        return data
    except (json.JSONDecodeError, OSError):
        return []


def save_manifest(manifest: list[dict[str, Any]]) -> None:
    """Atomically write the manifest."""
    mp = _manifest_path()
    tmp = mp.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(manifest, f, indent=2, default=str)
    os.replace(tmp, mp)


def upsert_manifest_entry(
    session_id: str,
    *,
    model: str = "",
    turn_count: int = 0,
    title: str | None = None,
    first_user_message: str = "",
) -> None:
    """Create or update a manifest entry for *session_id*."""
    manifest = load_manifest()

    # Find existing entry
    for entry in manifest:
        if entry.get("session_id") == session_id:
            entry["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            if model:
                entry["model"] = model
            entry["turn_count"] = turn_count
            if title is not None:
                entry["title"] = title
            if first_user_message and not entry.get("first_user_message"):
                entry["first_user_message"] = first_user_message[:200]
            save_manifest(manifest)
            return

    # New entry
    entry: dict[str, Any] = {
        "session_id": session_id,
        "file": f"{session_id}.json",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model,
        "turn_count": turn_count,
        "title": title,
        "first_user_message": first_user_message[:200] if first_user_message else "",
    }
    manifest.append(entry)
    save_manifest(manifest)


def rename_session_title(session_id: str, new_title: str) -> bool:
    """Rename a session's title in the manifest.  Returns False if not found."""
    manifest = load_manifest()
    for entry in manifest:
        if entry.get("session_id") == session_id:
            entry["title"] = new_title
            entry["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            save_manifest(manifest)
            return True
    return False


def remove_manifest_entry(session_id: str) -> None:
    """Remove a session from the manifest and delete its file."""
    manifest = load_manifest()
    manifest = [e for e in manifest if e.get("session_id") != session_id]
    save_manifest(manifest)
    sp = _session_path(session_id)
    try:
        sp.unlink(missing_ok=True)
    except OSError:
        pass


# ── Session file I/O ────────────────────────────────────────────────


def save_session(
    session_id: str,
    messages: list[dict[str, Any]],
    *,
    model: str = "",
    title: str | None = None,
    first_user_message: str = "",
) -> None:
    """Write *messages* to the session file and update the manifest.

    This overwrites the session file — it is designed to be called after
    every assistant response for crash resilience.
    """
    sp = _session_path(session_id)
    tmp = sp.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(messages, f, indent=2, default=str)
    os.replace(tmp, sp)

    # Count turns (user messages = turns)
    turn_count = sum(1 for m in messages if m.get("role") == "user")

    upsert_manifest_entry(
        session_id,
        model=model,
        turn_count=turn_count,
        title=title,
        first_user_message=first_user_message,
    )


def load_session(session_id: str) -> list[dict[str, Any]] | None:
    """Load messages from a session file, or None if not found."""
    sp = _session_path(session_id)
    if not sp.exists():
        return None
    try:
        with open(sp) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# ── Migration: old logs → sessions ──────────────────────────────────

_LOG_FILE_RE = re.compile(r"^session_(.+)\.json$")
_MIGRATION_SENTINEL = ".copane_logs_migrated"


def _logs_dir() -> Path:
    return Path.home() / ".copane" / "logs"


def migrate_logs_to_sessions() -> dict[str, int]:
    """Migrate old ``~/.copane/logs/session_*.json`` files into the
    session store.

    Old log files are **left in place** — callers can delete them
    manually once they're satisfied.  A sentinel file tracks which
    individual log files have already been migrated, so removing the
    sentinel and re-running won't create duplicates.

    Returns a dict ``{"migrated": N, "skipped": M, "failed": F}``.
    """
    logs_dir = _logs_dir()
    sessions_dir = _sessions_dir()
    sentinel = sessions_dir / _MIGRATION_SENTINEL

    result = {"migrated": 0, "skipped": 0, "failed": 0}

    if not logs_dir.exists():
        sentinel.touch(exist_ok=True)
        return result

    # Load the set of already-migrated log filenames
    migrated_filenames: set[str] = set()
    if sentinel.exists():
        try:
            with open(sentinel) as f:
                migrated_filenames = set(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass

    manifest = load_manifest()

    # Collect candidate files sorted by mtime (oldest first)
    candidates: list[Path] = []
    for path in logs_dir.glob("session_*.json"):
        if not _LOG_FILE_RE.match(path.name):
            continue
        # Skip files already migrated in a previous run
        if path.name in migrated_filenames:
            result["skipped"] += 1
            continue
        candidates.append(path)
    candidates.sort(key=lambda p: p.stat().st_mtime)

    for path in candidates:
        # Derive a session_id from the file's modification time
        mtime = path.stat().st_mtime
        ts = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(mtime))
        short = uuid.uuid4().hex[:6]
        session_id = f"{ts}-{short}"

        # Parse the old log file
        try:
            with open(path) as f:
                messages = json.load(f)
            if not isinstance(messages, list):
                raise ValueError("Not a JSON array")
        except (json.JSONDecodeError, OSError, ValueError) as e:
            result["failed"] += 1
            print(f"[migrate] Failed to parse {path.name}: {e}")
            continue

        if not messages:
            result["skipped"] += 1
            migrated_filenames.add(path.name)
            continue

        # Extract metadata from messages
        first_user = ""
        for m in messages:
            if m.get("role") == "user":
                first_user = m.get("content", "")
                break

        turn_count = sum(1 for m in messages if m.get("role") == "user")

        # Write session file
        sp = sessions_dir / f"{session_id}.json"
        tmp = sp.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(messages, f, indent=2, default=str)
        os.replace(tmp, sp)

        # Create manifest entry
        upsert_manifest_entry(
            session_id,
            model="imported",
            turn_count=turn_count,
            title=None,
            first_user_message=first_user,
        )
        migrated_filenames.add(path.name)
        result["migrated"] += 1

    # Persist the list of migrated filenames
    if migrated_filenames:
        with open(sentinel, "w") as f:
            json.dump(sorted(migrated_filenames), f)

    if result["migrated"]:
        print(
            f"[migrate] Migrated {result['migrated']} log(s) → "
            f"~/.copane/sessions/ (old logs left in ~/.copane/logs/)"
        )
    if result["skipped"]:
        print(f"[migrate] Skipped {result['skipped']} log(s) (already migrated)")
    if result["failed"]:
        print(f"[migrate] Failed {result['failed']} log(s)")

    return result
