"""
Session store for copane — manages session files and manifest.

Each session is stored as a JSONL file under ``~/.copane/sessions/``.
A ``manifest.json`` in the same directory tracks all sessions.

Messages are appended one JSON line at a time after each assistant
response.  No full rewrites — the disk file always contains the
complete conversation for ``/view``, while the in-memory copy may be
trimmed by the agent to bound token usage.

Legacy ``.json`` files (v1/v2) are migrated to ``.jsonl`` on first load.
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
    path = Path.home() / ".copane" / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _manifest_path() -> Path:
    return _sessions_dir() / "manifest.json"


def _session_path(session_id: str) -> Path:
    return _sessions_dir() / f"{session_id}.jsonl"


def _legacy_session_path(session_id: str) -> Path:
    """Old ``.json`` session files (v1 bare-array, v2 dict wrapper)."""
    return _sessions_dir() / f"{session_id}.json"


def session_file_path(session_id: str) -> Path:
    """Public accessor for the session file path (JSONL)."""
    return _session_path(session_id)


def legacy_session_path(session_id: str) -> Path:
    """Public accessor for the legacy ``.json`` session path."""
    return _legacy_session_path(session_id)


def generate_session_id() -> str:
    """Generate a unique, human-readable session id.

    Format: ``YYYY-MM-DD_HH-MM-SS-<6-char-hex>``
    """
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    short = uuid.uuid4().hex[:6]
    return f"{ts}-{short}"


# ── Manifest helpers ────────────────────────────────────────────────


def load_manifest() -> list[dict[str, Any]]:
    mp = _manifest_path()
    if not mp.exists():
        return []
    try:
        with open(mp) as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        data.sort(key=lambda e: e.get("last_updated", ""), reverse=True)
        return data
    except (json.JSONDecodeError, OSError):
        return []


def save_manifest(manifest: list[dict[str, Any]]) -> None:
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
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    manifest = load_manifest()

    for entry in manifest:
        if entry.get("session_id") == session_id:
            entry["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            if model:
                entry["model"] = model
            entry["turn_count"] = turn_count
            entry["input_tokens"] = input_tokens
            entry["output_tokens"] = output_tokens
            if title is not None:
                entry["title"] = title
            if first_user_message and not entry.get("first_user_message"):
                entry["first_user_message"] = first_user_message[:200]
            save_manifest(manifest)
            return

    entry: dict[str, Any] = {
        "session_id": session_id,
        "file": f"{session_id}.jsonl",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model,
        "turn_count": turn_count,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "title": title,
        "first_user_message": first_user_message[:200] if first_user_message else "",
    }
    manifest.append(entry)
    save_manifest(manifest)


def rename_session_title(session_id: str, new_title: str) -> bool:
    manifest = load_manifest()
    for entry in manifest:
        if entry.get("session_id") == session_id:
            entry["title"] = new_title
            entry["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            save_manifest(manifest)
            return True
    return False


def remove_manifest_entry(session_id: str) -> None:
    manifest = load_manifest()
    manifest = [e for e in manifest if e.get("session_id") != session_id]
    save_manifest(manifest)
    sp = _session_path(session_id)
    try:
        sp.unlink(missing_ok=True)
    except OSError:
        pass
    # Clean up legacy .json file too
    lp = _legacy_session_path(session_id)
    try:
        lp.unlink(missing_ok=True)
    except OSError:
        pass


# ── Migration helper ────────────────────────────────────────────────

def _migrate_legacy(session_id: str) -> list[dict[str, Any]] | None:
    """If a legacy ``.json`` session file exists, read it and write to ``.jsonl``.

    The old ``.json`` is **deleted** after successful migration.
    Returns the messages list, or None if no legacy file was found.
    """
    lp = _legacy_session_path(session_id)
    if not lp.exists():
        return None

    try:
        with open(lp) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    messages: list[dict] = []
    if isinstance(data, list):
        messages = data
    elif isinstance(data, dict):
        messages = data.get("messages", [])

    # Write to JSONL
    sp = _session_path(session_id)
    with open(sp, "w") as f:
        for m in messages:
            f.write(json.dumps(m, default=str) + "\n")

    # Delete legacy file
    try:
        lp.unlink()
    except OSError:
        pass

    return messages


# ── Session file I/O ────────────────────────────────────────────────


def save_session(
    session_id: str,
    messages: list[dict[str, Any]],
    *,
    model: str = "",
    title: str | None = None,
    first_user_message: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    append: bool = False,
) -> None:
    """Write *messages* to the session file and update the manifest.

    Parameters
    ----------
    append:
        If ``False`` (default), the file is rewritten with *messages*.
        If ``True``, *messages* are appended line-by-line to the JSONL
        file.  This is the normal code path — the agent appends only
        the current turn's new messages after each assistant response.
    """
    sp = _session_path(session_id)

    if append and sp.exists():
        with open(sp, "a") as f:
            for m in messages:
                f.write(json.dumps(m, default=str) + "\n")
    else:
        tmp = sp.with_suffix(".tmp")
        with open(tmp, "w") as f:
            for m in messages:
                f.write(json.dumps(m, default=str) + "\n")
        os.replace(tmp, sp)

    # Count turns
    if append:
        # Derive from the manifest + incoming batch (no file re-read)
        manifest = load_manifest()
        existing = 0
        for entry in manifest:
            if entry.get("session_id") == session_id:
                existing = entry.get("turn_count", 0)
                break
        new_turns = sum(1 for m in messages if m.get("role") == "user")
        turn_count = existing + new_turns
    else:
        turn_count = sum(1 for m in messages if m.get("role") == "user")

    upsert_manifest_entry(
        session_id,
        model=model,
        turn_count=turn_count,
        title=title,
        first_user_message=first_user_message,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def load_session(session_id: str) -> list[dict[str, Any]] | None:
    """Load messages from a session file, or None if not found.

    Reads the JSONL file line by line.  If only a legacy ``.json``
    file exists, migrates it first.
    """
    # Try migration first
    migrated = _migrate_legacy(session_id)
    if migrated is not None:
        return migrated

    sp = _session_path(session_id)
    if not sp.exists():
        return None

    messages: list[dict] = []
    try:
        with open(sp) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                messages.append(json.loads(line))
    except (json.JSONDecodeError, OSError):
        return None

    return messages if messages else None


def load_session_meta(session_id: str) -> dict[str, Any] | None:
    """Return metadata dict with ``input_tokens`` and ``output_tokens``.

    Token counts are sourced from the manifest, not the file.
    """
    manifest = load_manifest()
    for entry in manifest:
        if entry.get("session_id") == session_id:
            return {
                "input_tokens": entry.get("input_tokens", 0),
                "output_tokens": entry.get("output_tokens", 0),
            }
    return None


# ── Migration: old logs → sessions ──────────────────────────────────

_LOG_FILE_RE = re.compile(r"^session_(.+)\.json$")
_MIGRATION_SENTINEL = ".copane_logs_migrated"


def _logs_dir() -> Path:
    return Path.home() / ".copane" / "logs"


def migrate_logs_to_sessions() -> dict[str, int]:
    """DEPRECATED: One-shot migration from v1 log files to v2 session store.

    Old log files are **left in place**.
    """
    logs_dir = _logs_dir()
    sessions_dir = _sessions_dir()
    sentinel = sessions_dir / _MIGRATION_SENTINEL

    result = {"migrated": 0, "skipped": 0, "failed": 0}

    if not logs_dir.exists():
        sentinel.touch(exist_ok=True)
        return result

    migrated_filenames: set[str] = set()
    if sentinel.exists():
        try:
            with open(sentinel) as f:
                migrated_filenames = set(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass

    candidates: list[Path] = []
    for path in logs_dir.glob("session_*.json"):
        if not _LOG_FILE_RE.match(path.name):
            continue
        if path.name in migrated_filenames:
            result["skipped"] += 1
            continue
        candidates.append(path)
    candidates.sort(key=lambda p: p.stat().st_mtime)

    for path in candidates:
        mtime = path.stat().st_mtime
        ts = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(mtime))
        short = uuid.uuid4().hex[:6]
        session_id = f"{ts}-{short}"

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

        first_user = ""
        for m in messages:
            if m.get("role") == "user":
                first_user = m.get("content", "")
                break

        turn_count = sum(1 for m in messages if m.get("role") == "user")

        sp = sessions_dir / f"{session_id}.jsonl"
        tmp = sp.with_suffix(".tmp")
        with open(tmp, "w") as f:
            for m in messages:
                f.write(json.dumps(m, default=str) + "\n")
        os.replace(tmp, sp)

        upsert_manifest_entry(
            session_id,
            model="imported",
            turn_count=turn_count,
            title=None,
            first_user_message=first_user,
            input_tokens=0,
            output_tokens=0,
        )
        migrated_filenames.add(path.name)
        result["migrated"] += 1

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
