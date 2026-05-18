"""Completers for the copane interactive REPL.

Provides multi-mode completion for:
  - @filename path completion (delegates to FileCompleter)
  - Slash commands (/switch, /clear, /models, /renderer, /sessions,
    /resume, /view, /delete, /rename, /modelinfo, /help)
  - Model keys after /switch <key>
  - Renderer keys after /renderer <key>
  - Session IDs after /resume, /view, /delete, /rename
"""

from __future__ import annotations

import re

from prompt_toolkit.completion import Completer, Completion

from copane.file_utils import FileCompleter
from copane.model_config import ModelConfig
from copane.renderers import AVAILABLE_RENDERERS
from copane import session_store


class CommandCompleter(Completer):
    """Completes slash commands in the copane REPL.

    Activates when the line starts with '/' and there's no space yet
    (meaning the user is still typing the command name).
    """

    COMMANDS = [
        "/switch", "/renderer", "/clear", "/models", "/modelinfo",
        "/help", "/sessions", "/resume", "/view", "/delete", "/rename",
    ]

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Only activate for slash commands without a space (still typing
        # the command).  Exception: /resume, /view, /delete and /rename
        # accept a session-id arg, but the command name itself must not
        # contain a space.
        if not text.startswith("/"):
            return

        # Find where the command name ends
        space_idx = text.find(" ")
        prefix = text if space_idx == -1 else text[:space_idx]

        for cmd in self.COMMANDS:
            if cmd.startswith(prefix):
                yield Completion(
                    cmd,
                    start_position=-len(prefix),
                    display=cmd,
                    style="bg:default",
                )


class ModelKeyCompleter(Completer):
    """Completes model keys after '/switch '.

    Reads the list of available model keys from the user's model config
    and offers them as completions after the user has typed '/switch '.
    """

    def __init__(self):
        self._model_keys: list[str] | None = None
        self._model_config = ModelConfig()

    def _refresh_keys(self):
        """Load model keys from the configuration file."""
        models = self._model_config.get_available_models()
        self._model_keys = sorted(models.keys())

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Match /switch followed by a space and optional partial key
        m = re.match(r"^/switch\s+(\S*)$", text)
        if not m:
            return

        prefix = m.group(1)
        self._refresh_keys()

        if not self._model_keys:
            return

        for key in self._model_keys:
            if key.startswith(prefix):
                yield Completion(
                    key,
                    start_position=-len(prefix),
                    display=key,
                    style="bg:default",
                )


class RendererKeyCompleter(Completer):
    """Completes renderer names after '/renderer '.

    Reads the list of available renderers from AVAILABLE_RENDERERS
    and offers them as completions.
    """

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Match /renderer followed by a space and optional partial key
        m = re.match(r"^/renderer\s+(\S*)$", text)
        if not m:
            return

        prefix = m.group(1)

        for key in sorted(AVAILABLE_RENDERERS):
            if key.startswith(prefix):
                yield Completion(
                    key,
                    start_position=-len(prefix),
                    display=key,
                    style="bg:default",
                )


class SessionIdCompleter(Completer):
    """Completes session IDs after commands that take a session-id arg.

    Supports /resume, /view, /delete, and /rename.  Matches against
    session IDs from the manifest (prefix match).  Also shows the
    session title or first-user-message as display metadata so the
    user can disambiguate.
    """

    def __init__(self):
        self._trigger_commands = {"resume", "view", "delete", "rename"}

    def _load_sessions(self) -> list[dict]:
        """Return sorted manifest entries (most recent first)."""
        return session_store.load_manifest()

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Match /<cmd> <partial-or-full-session-id>
        # The /rename command takes TWO args: /rename <id> <title>, so
        # we only complete the first arg (until a second space appears).
        m = re.match(r"^/(\w+)\s+(\S*)$", text)
        if not m:
            return

        cmd = m.group(1)
        if cmd not in self._trigger_commands:
            return

        # For /rename, if there are already two args (id + title), don't
        # complete further — the user is typing the title.
        if cmd == "rename":
            rest = text[len(f"/rename "):]
            if " " in rest.lstrip():
                return  # already has both args

        prefix = m.group(2)

        for entry in self._load_sessions():
            sid = entry.get("session_id", "")
            if not sid.startswith(prefix):
                continue

            # Build a display line with metadata so the user can pick
            title = entry.get("title") or ""
            if not title:
                title = entry.get("first_user_message", "")[:60]
            model = (entry.get("model") or "").split("/")[-1]
            turns = entry.get("turn_count", 0)
            display = f"{sid[:19]}  {model}  t:{turns}  {title}"

            yield Completion(
                sid,
                start_position=-len(prefix),
                display=display,
                style="bg:default",
            )


class CopaneCompleter(Completer):
    """Multi-mode completer for the copane REPL.

    Inspects the document context and delegates to the appropriate
    sub-completer:
      - @filename → FileCompleter
      - /command  → CommandCompleter
      - /switch <partial> → ModelKeyCompleter
      - /renderer <partial> → RendererKeyCompleter
      - /resume|/view|/delete|/rename <partial> → SessionIdCompleter
    """

    def __init__(self):
        self.file_completer = FileCompleter()
        self.command_completer = CommandCompleter()
        self.model_key_completer = ModelKeyCompleter()
        self.renderer_key_completer = RendererKeyCompleter()
        self.session_id_completer = SessionIdCompleter()

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Mode 1: @-file completion
        if re.search(r"@\S*$", text):
            yield from self.file_completer.get_completions(document, complete_event)

        # Mode 2: Slash commands — only when no space yet (still typing the command)
        if text.startswith("/") and " " not in text:
            yield from self.command_completer.get_completions(document, complete_event)

        # Mode 3: After /switch — model key completion
        if re.match(r"^/switch\s+", text):
            yield from self.model_key_completer.get_completions(document, complete_event)

        # Mode 4: After /renderer — renderer key completion
        if re.match(r"^/renderer\s+", text):
            yield from self.renderer_key_completer.get_completions(document, complete_event)

        # Mode 5: After /resume, /view, /delete, /rename — session-id completion
        if re.match(r"^/(resume|view|delete|rename)\s+", text):
            yield from self.session_id_completer.get_completions(document, complete_event)
