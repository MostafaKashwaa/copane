"""File inclusion and completion utilities for copane."""

from __future__ import annotations

import os
import re
from pathlib import Path

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import ANSI

from .term_styles import Colors, print_error, print_success, print_warning


class FileCompleter(Completer):
    """Enhanced file completer with colors and sub-directory support."""

    def get_completions(self, document: Document, complete_event):
        text_before_cursor = document.text_before_cursor
        pattern = r"@(\S*)$"
        match = re.search(pattern, text_before_cursor)

        if not match:
            return

        full_prefix = match.group(1)

        if not full_prefix:
            # Just typed @, list current directory
            base_dir = '.'
            search_prefix = ''
        # Handle both forward and backward slashes
        elif '/' in full_prefix or '\\' in full_prefix:
            normalized = full_prefix.replace('\\', '/')
            last_slash = normalized.rfind('/')
            dir_part = normalized[:last_slash]
            file_prefix = normalized[last_slash + 1:]

            if dir_part == '':
                dir_part = '.'
            if not os.path.isdir(dir_part):
                return
            base_dir = dir_part
            search_prefix = file_prefix
        else:
            base_dir = '.'
            search_prefix = full_prefix

        try:
            for entry in sorted(os.listdir(base_dir)):
                # Skip hidden files unless explicitly typed
                if entry.startswith('.') and not search_prefix.startswith('.'):
                    continue

                if entry.lower().startswith(search_prefix.lower()):
                    full_path = os.path.join(base_dir, entry)

                    # Determine display text with colors
                    if os.path.isfile(full_path):
                        display_text = ANSI(
                            f"{Colors.PRIMARY}{entry}{Colors.RESET}")
                    elif os.path.isdir(full_path):
                        display_text = ANSI(
                            f"{Colors.ACCENT}{entry}/{Colors.RESET}")
                    else:
                        display_text = entry

                    # Determine completion text
                    if '/' in full_prefix or '\\' in full_prefix:
                        if dir_part == '.':
                            completion_text = entry
                        else:
                            completion_text = os.path.join(
                                dir_part, entry).replace('\\', '/')
                    else:
                        completion_text = entry

                    yield Completion(
                        completion_text,
                        start_position=-len(full_prefix),
                        display=display_text,
                        style="bg:default"
                    )
        except (PermissionError, FileNotFoundError, OSError):
            return


def _looks_like_path(token: str) -> bool:
    """Heuristic: does @token look like a file path?

    Returns True if the token contains a dot (e.g. @main.py, @.env)
    or a slash (e.g. @src/main.py, @./config.json).
    This avoids false warnings for casual mentions like @someone or @param.
    """
    return '.' in token or '/' in token or '\\' in token


def expand_files(text: str) -> str:
    """Find all occurrences of @filename and replace with file content.

    For each @token in the input:
      1. Try to read the file. If it exists, replace with its contents.
      2. If the file doesn't exist and the token *looks like a file path*
         (contains '.' or '/' or '\\'), print a warning and replace with
         an error marker.
      3. If the file doesn't exist and the token does NOT look like a file
         path, silently leave it as-is (likely a casual mention like @someone).

    The heuristic in step 2 avoids false warnings for common non-file uses
    of the @ sign while still alerting the user when a genuine file reference
    likely failed.
    """
    pattern = r"@(\S+)"
    matches = re.findall(pattern, text)

    for raw_token in matches:
        token = raw_token.rstrip('.,;:!?)]}')
        if not token:
            continue

        if os.path.isfile(token):
            try:
                with open(token, "r") as f:
                    content = f.read()
                text = text.replace(f"@{raw_token}", content)
                print_success(f"Included file: {token}")
            except Exception as e:
                print_error(f"Error reading {token}: {e}")
                text = text.replace(
                    f"@{raw_token}", f"[error reading file: {token}]")
        else:
            if _looks_like_path(token):
                print_warning(f"File not found: {token}")
                text = text.replace(
                    f"@{raw_token}", f"[error: file not found: {token}]")
            # Otherwise silently ignore — leave the text as-is
    return text
