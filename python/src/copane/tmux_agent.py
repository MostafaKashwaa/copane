#!/usr/bin/env python3
"""
tmux-agent: AI agent configuration for terminal-based coding assistance.
Enhanced with professional model selection and configuration management.

Conversation memory is managed through turn-boundary summarization:
file-read results from the previous turn are compressed to metadata
stubs (path, line count, purpose hint) so memory stays O(one turn).
"""

import logging
import os
import json
import sys
import gc
import time
from pathlib import Path
from typing import Dict, Any

from agents import Agent, OpenAIChatCompletionsModel, RawResponsesStreamEvent, RunItemStreamEvent, RunState, Tool, Runner, ToolApprovalItem
from openai import AsyncOpenAI
from openai.types.responses import ResponseReasoningSummaryTextDeltaEvent, ResponseReasoningTextDeltaEvent, ResponseTextDeltaEvent

from langsmith import traceable

from copane.tools import (
    get_current_dir,
    grep_files,
    list_files,
    read_file,
    run_command,
    write_file,
    TOOL_SUMMARIZERS,
)

# ---------------------------------------------------------------------------
# Memory safety limits
# ---------------------------------------------------------------------------

# Hard message-count cap (never allow more than this, regardless of byte
# budget).  Each turn adds 2-3 messages (user, reasoning, assistant).
# After turn-boundary summarization this should never fire in normal use.
MAX_MESSAGES = 100

# When we exceed MAX_MESSAGES we trim back to this fraction of MAX
# so we don't trim on every single add_message call.
TRIM_TARGET_FRACTION = 0.75

# Byte budget for the entire message history (tool outputs included).
# Raised to 5 MB now that turn-boundary summarization keeps normal
# conversations well under 1 MB.  This is a circuit breaker, not flow
# control.
MAX_HISTORY_BYTES = 5_000_000  # 5 MB

# When we trim due to byte budget, we keep this many of the most recent
# messages.  This ensures the model retains recent context.
KEEP_RECENT_MESSAGES = 20

# Reasoning / chain-of-thought text can be enormous (50-100 KB per turn
# for DeepSeek-R1 style models).  We store only the tail of each
# reasoning block so history doesn't blow up.
MAX_REASONING_CHARS = 8_000

MAX_TOOL_TURNS = 50  # max turns for a single tool-using response

# Internal metadata fields that must be stripped before sending
# messages to the model API.  The SDK's chatcmpl_converter rejects
# any dict whose keys are not exactly {"role", "content"}.
_INTERNAL_FIELDS = frozenset({
    "_turn_id",
    "_tool_name",
    "_tool_args",
    "_tool_truncated",
    "_is_summary",
})


class ModelConfig:
    """Configuration for AI models with professional management."""

    def __init__(self):
        self.config_dir = Path.home() / ".config" / "tmux-agent"
        self.config_file = self.config_dir / "model_config.json"
        self.default_config = {
            "selected_model": "deepseek-chat",
            "available_models": {
                "deepseek-chat": {
                    "type": "api",
                    "base_url": "https://api.deepseek.com/v1",
                    "model_name": "deepseek-chat",
                    "env_key": "DEEPSEEK_API_KEY",
                    "description": "DeepSeek Chat (Default)"
                },
                "gpt-4o": {
                    "type": "api",
                    "base_url": "https://api.openai.com/v1",
                    "model_name": "gpt-4o",
                    "env_key": "OPENAI_API_KEY",
                    "description": "OpenAI GPT-4o"
                },
                "local-ollama": {
                    "type": "local",
                    "base_url": "http://localhost:11434/v1",
                    "model_name": "gemma4:26b",
                    "env_key": "",
                    "description": "Local Ollama (gemma4:26b)"
                }
            }
        }
        self._ensure_config()

    def _ensure_config(self):
        """Ensure configuration directory and file exist."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        if not self.config_file.exists():
            self.save_config(self.default_config)

    def load_config(self) -> Dict[str, Any]:
        """Load configuration from file."""
        try:
           
            with open(self.config_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return self.default_config

    def save_config(self, config: Dict[str, Any]):
        """Save configuration to file."""
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=2)

    def get_selected_model(self) -> str:
        """Get the currently selected model."""
        config = self.load_config()
        return config.get("selected_model", "deepseek-chat")

    def set_selected_model(self, model_key: str):
        """Set the selected model."""
        config = self.load_config()
        if model_key in config.get("available_models", {}):
            config["selected_model"] = model_key
            self.save_config(config)
        else:
            raise ValueError(
                f"Model '{model_key}' not found in available models")

    def get_available_models(self) -> Dict[str, Dict[str, Any]]:
        """Get all available models."""
        config = self.load_config()
        return config.get("available_models", {})

    def add_custom_model(self, key: str, model_config: Dict[str, Any]):
        """Add a custom model configuration."""
        config = self.load_config()
        config["available_models"][key] = model_config
        self.save_config(config)

    def remove_model(self, key: str):
        """Remove a model configuration."""
        config = self.load_config()
        if key in config.get("available_models", {}):
            del config["available_models"][key]
            # If we're removing the selected model, fall back to default
            if config.get("selected_model") == key:
                config["selected_model"] = "deepseek-chat"
            self.save_config(config)


class TmuxAgent:
    """TmuxAgent is an AI coding assistant that runs inside a tmux pane.

    Conversation memory is managed through turn-boundary summarization:
    file-read results from the previous turn are compressed to metadata
    stubs so memory stays O(one turn), not O(total conversation).
    """

    def __init__(self, name):
        self.name = name
        self.messages: list[dict] = []
        self.agent: Agent | None = None
        self.tools: list[Tool] = [
            read_file,
            run_command,
            grep_files,
            list_files,
            write_file,
            get_current_dir
        ]
        self.model_config = ModelConfig()
        self._trim_warned = False  # only warn once about trimming
        self._turn_id: int = 0     # incremented on each user message

    # ── Full-history persistence ────────────────────────────────────

    def _save_full_history(self):
        """Write the complete message list to disk before summarization.

        Saved to ``~/.copane/logs/session_<timestamp>.json``.
        Creates the directory if it doesn't exist.
        """
        logs_dir = Path.home() / ".copane" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        path = logs_dir / f"session_{ts}.json"
        try:
            with open(path, "w") as f:
                json.dump(self.messages, f, indent=2, default=str)
        except (TypeError, OSError, IOError) as e:
            logging.warning("Failed to save full history: %s", e)

    # ── Turn-boundary summarization ─────────────────────────────────

    def _build_summary(self, turn_tools: dict) -> str | None:
        """Build a metadata summary block from grouped tool outputs.

        Dispatches to per-tool ``summarize()`` functions defined
        alongside each tool (see ``tools/__init__.py`` for the
        ``TOOL_SUMMARIZERS`` registry).  Section headers are defined
        here in the agent — they are a presentation concern, not a
        tool concern.
        """
        _SECTION_HEADERS = {
            "read_file": "Files read:",
            "grep_files": "Searches:",
            "run_command": "Commands run:",
            "list_files": "Directories listed:",
            "write_file": "Files written:",
        }

        lines = ["[PREVIOUS TURN — tool outputs summarized]", ""]
        any_content = False

        for tool_name, items in turn_tools.items():
            summarizer = TOOL_SUMMARIZERS.get(tool_name)
            if summarizer is None:
                continue

            section_lines = []
            for item in items:
                args = item.get("_tool_args", {})
                output = item.get("content", "")
                line = summarizer(args, output)
                if line is not None:
                    section_lines.append(f"  {line}")

            if section_lines:
                header = _SECTION_HEADERS.get(tool_name)
                if header:
                    lines.append(header)
                lines.extend(section_lines)
                lines.append("")
                any_content = True

        if not any_content:
            return None  # nothing to summarize

        lines.append(
            "(Use read_file to re-read any file if exact content is needed.)")
        return "\n".join(lines)

    def _summarize_previous_turn(self):
        """Compress tool outputs from the previous turn into metadata.

        Called at the start of ``add_message()`` when the new message is
        from the user (i.e. a turn boundary).  Saves full history to disk
        first, then replaces the previous turn's tool-output messages
        with a single summary.
        """
        if self._turn_id == 0:
            return  # first turn — nothing to summarize

        # Save full history before modifying it
        self._save_full_history()

        prev_turn = self._turn_id  # current turn ID before increment

        # Collect all messages from the previous turn
        prev_messages = [
            m for m in self.messages
            if m.get("_turn_id") == prev_turn
        ]

        # Group tool-output messages by tool name
        turn_tools: dict[str, list[dict]] = {}
        for m in prev_messages:
            if m.get("role") == "tool":
                tool_name = m.get("_tool_name", "unknown")
                turn_tools.setdefault(tool_name, []).append(m)

        if not turn_tools:
            return  # no tool outputs to summarize

        # Build summary
        summary = self._build_summary(turn_tools)
        if summary is None:
            return

        # Find the last user message of the previous turn (to insert
        # the summary after it).  The summary should appear right after
        # the user message, before any tool calls or assistant response.
        last_user_idx = None
        for i, m in enumerate(self.messages):
            if m.get("_turn_id") == prev_turn and m.get("role") == "user":
                last_user_idx = i

        if last_user_idx is None:
            return  # should not happen

        # Now remove all tool-output messages from the previous turn.
        # We must do this in reverse order to preserve indices.
        indices_to_remove = [
            i for i, m in enumerate(self.messages)
            if m.get("_turn_id") == prev_turn and m.get("role") == "tool"
        ]
        for i in reversed(indices_to_remove):
            self.messages.pop(i)

        # Recalculate insert position after removals
        new_last_user_idx = None
        for i, m in enumerate(self.messages):
            if m.get("_turn_id") == prev_turn and m.get("role") == "user":
                new_last_user_idx = i

        if new_last_user_idx is not None:
            summary_msg = {
                "role": "system",
                "content": summary,
                "_turn_id": prev_turn,
                "_is_summary": True,
            }
            self.messages.insert(new_last_user_idx + 1, summary_msg)

    # ── Message / memory management ─────────────────────────────────

    @staticmethod
    def _strip_internal_fields(messages: list[dict]) -> list[dict]:
        """Return a shallow copy of *messages* with internal metadata
        fields (``_turn_id``, ``_tool_name``, etc.) removed.

        The OpenAI Agents SDK chat completion converter rejects dicts
        whose keys are not exactly ``{"role", "content"}`` (see
        ``maybe_easy_input_message`` in ``chatcmpl_converter.py``).
        This helper produces clean dicts safe for the model API while
        keeping the internal fields on ``self.messages`` for
        turn-boundary summarization.
        """
        return [
            {k: v for k, v in m.items() if k not in _INTERNAL_FIELDS}
            for m in messages
        ]

    def _estimate_total_bytes(self) -> int:
        """Estimate the total byte size of the full message history.

        Walks every message and sums the length of all text fields
        (role, content, reasoning summaries, tool outputs, etc.).
        """
        try:
            total = 0
            for m in self.messages:
                # Quick path: str-ify the whole message (fast enough for
                # the typical 50-100 message case).
                total += len(str(m))
            return total
        except (TypeError, AttributeError, KeyError):
            return 0

    def _trim_by_byte_budget(self):
        """Aggressively trim old messages when the byte budget is exceeded.

        Keeps the most recent KEEP_RECENT_MESSAGES and drops everything
        older.  This is a last-resort safety valve — normal trimming
        happens via _trim_messages (message-count based).
        """
        total = self._estimate_total_bytes()
        if total <= MAX_HISTORY_BYTES:
            return

        if not self._trim_warned:
            print(
                f"\n⚠ [copane] Message history too large (~{total / 1_000_000:.1f} MB). "
                f"Trimming oldest messages to prevent OOM. "
                f"Use /clear to reset.\n",
                file=sys.stderr, flush=True,
            )
            self._trim_warned = True

        keep = min(KEEP_RECENT_MESSAGES, len(self.messages))
        dropped = len(self.messages) - keep
        self.messages = self.messages[-keep:] if keep else []
        logging.warning(
            "Byte-budget trim: dropped %d messages, kept %d (~%d KB now)",
            dropped, keep, self._estimate_total_bytes() // 1024,
        )

    def _trim_messages(self):
        """Trim old messages when we exceed MAX_MESSAGES.

        Trims back to TRIM_TARGET_FRACTION of MAX so we don't trim on
        every single add_message call.  Warns once the first time
        trimming occurs.
        """
        if len(self.messages) <= MAX_MESSAGES:
            return

        if not self._trim_warned:
            print(
                f"\n⚠ [copane] Message history full ({len(self.messages)}). "
                f"Trimming oldest messages to conserve memory. "
                f"Use /clear to reset.\n",
                file=sys.stderr, flush=True,
            )
            self._trim_warned = True

        target = int(MAX_MESSAGES * TRIM_TARGET_FRACTION)
        trimmed = len(self.messages) - target
        self.messages = self.messages[trimmed:]

    def _estimate_memory_mb(self) -> float:
        """Rough estimate of memory used by self.messages (MB)."""
        return self._estimate_total_bytes() / (1024 * 1024)

    # ── Model management ────────────────────────────────────────────

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the current model."""
        selected_key = self.model_config.get_selected_model()
        models = self.model_config.get_available_models()
        model_info = models.get(selected_key, {})

        return {
            "key": selected_key,
            "name": model_info.get("model_name", selected_key),
            "description": model_info.get("description", "Unknown model"),
            "type": model_info.get("type", "unknown"),
            "base_url": model_info.get("base_url", ""),
            "env_key": model_info.get("env_key", ""),
            "status": self._check_model_status(model_info)
        }

    def _check_model_status(self, model_info: Dict[str, Any]) -> str:
        """Check the availability status of a model."""
        env_key = model_info.get("env_key", "")

        if model_info.get("type") == "local":
            # Check if the local model's base URL is reachable (basic check for local availability)
            ollama_url = model_info.get("base_url")
            if ollama_url:
                try:
                    import httpx
                    response = httpx.get(ollama_url + "/models", timeout=2)
                    if response.status_code == 200:
                        return "available"
                    else:
                        return "unreachable (try running 'ollama serve' or correcting base_url)"
                except Exception:
                    return "unreachable"
            else:
                return "unavailable (local model missing base_url)"

        if env_key:
            api_key = os.getenv(env_key)
            if api_key:
                return "configured"
            else:
                return "missing_api_key"

        return "unknown"

    def list_available_models(self) -> Dict[str, Dict[str, Any]]:
        """List all available models with their status."""
        models = self.model_config.get_available_models()
        result = {}

        for key, config in models.items():
            status = self._check_model_status(config)
            result[key] = {
                "name": config.get("model_name", key),
                "description": config.get("description", ""),
                "type": config.get("type", "unknown"),
                "status": status,
                "is_selected": key == self.model_config.get_selected_model()
            }

        return result

    def switch_model(self, model_key: str):
        """Switch to a different model."""
        models = self.model_config.get_available_models()
        if model_key not in models:
            raise ValueError(
                f"Model '{model_key}' not found. Available models: {list(models.keys())}")

        self.model_config.set_selected_model(model_key)
        self.agent = None

    @traceable(name="Change Mode")
    def setup(self):
        """Setup the agent with the selected model."""
        selected_key = self.model_config.get_selected_model()
        models = self.model_config.get_available_models()
        model_config = models.get(selected_key, {})

        if not model_config:
            raise ValueError(
                f"Model configuration for '{selected_key}' not found")

        model_type = model_config.get("type")
        model_name = model_config.get("model_name", selected_key)
        base_url = model_config.get("base_url")
        env_key = model_config.get("env_key", "")

        if model_type == "api":
            api_key = os.getenv(env_key)
            if not api_key:
                raise ValueError(
                    f"API key for {selected_key} not found. "
                    f"Please set {env_key} in your .env file."
                )

            client = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
            )
            model = OpenAIChatCompletionsModel(
                model=model_name,
                openai_client=client,
            )

        elif model_type == "local":
            client = AsyncOpenAI(
                base_url=base_url,
                api_key="",
            )
            model = OpenAIChatCompletionsModel(
                model=model_name,
                openai_client=client,
            )

        else:
            raise ValueError(f"Unknown model type: {model_type}")

        self.agent = Agent(
            name=self.name,
            instructions="""
You are a coding assistant running inside a tmux pane.
The user will send you code snippets or questions from their editor.
You have tools to read files, run commands, and search code.
Tool outputs are JSON objects with a `success` boolean, an output string, an error_type string or null, 
and a `truncated` boolean indicates wheather the ouput is truncated.
Use the tools proactively — don't just answer from the snippet alone.
Before calling a tool, briefly say what you're about to do and why, in one natural sentence.
Read surrounding context, check imports, run tests, check git history
if it helps you give a better answer.

Be concise. Code first, explanation after.
If asked to modify code, show the diff or write the file directly.
If the you tried a tool that makes changes and needs approval, and the changes were not approved, do not retry, instead
ask the user about the reason for the rejection and how to proceed.

## Conversation memory

Between turns, file read results from the previous turn are summarized
to metadata (path, line count, purpose hint). Exact file contents are
NOT retained across turns.

- Gather all needed information from files within the current turn.
- At the start of a new turn, re-read key files if exact content is
  needed (one read_file call per file gets full contents).
- Use grep_files first to locate relevant sections, then read_file
  with start_line/end_line to zoom in.
""",
            tools=self.tools,
            model=model,
        )

    def add_message(self, role: str, content: str):
        """Add a message to the conversation history.

        At user-message boundaries (turn boundaries), summarizes tool
        outputs from the previous turn to keep memory bounded.
        """
        if role == "user":
            self._summarize_previous_turn()
            self._turn_id += 1

        msg: dict = {"role": role, "content": content, "_turn_id": self._turn_id}
        self.messages.append(msg)
        self._trim_messages()
        self._trim_by_byte_budget()

    def clear_messages(self):
        """Clear the conversation history."""
        self.messages = []
        self._trim_warned = False
        self._turn_id = 0

    def get_message_count(self) -> int:
        """Get the number of messages in the conversation history."""
        # Each turn typically consists of a user message, an optional reasoning message, and an assistant message.
        # We extract exactly the user and assistant messages for a more accurate turn count, ignoring reasoning messages.
        return sum(1 for m in self.messages if m.get("role") in ("user", "assistant"))

    def save_conversation(self, file_path: str):
        """Save the conversation history to a file."""
        with open(file_path, 'w') as f:
            json.dump(self.messages, f, indent=2)

    def handle_tool_approval(self, item: ToolApprovalItem, decision: str, state: RunState):
        """Approve or reject a tool call."""
        match decision:
            case 'y':
                state.approve(item)
            case 'n':
                state.reject(
                    item, rejection_message="User rejected this tool call. If you can't proceed without this tool call, stop trying and ask the user how to proceed."
                )
            case 'a':
                state.approve(item)
                # After approval, the runner will continue — we signal
                # to the UI that "always allow" was requested so it can
                # auto-approve subsequent tool calls in this round.
            case 'r':
                state.reject(
                    item, rejection_message="User requested retry with modifications. Try a different approach."
                )
            case 'q':
                raise RuntimeError(
                    "Tool approval process interrupted by user.")
            case _:
                raise ValueError(
                    f"Invalid decision: {decision}. Must be one of 'y', 'n', 'a', 'r', or 'q'.")

    # ── Streaming response ──────────────────────────────────────────

    @traceable(run_type='chain', name='Stream Response')
    async def stream_response(self, user_input: str):
        """Get a response from the agent based on user input."""
        if not self.agent:
            self.setup()

        self.add_message("user", user_input)

        response = Runner.run_streamed(
            self.agent,
            self._strip_internal_fields(self.messages),
            max_turns=MAX_TOOL_TURNS,
        )

        thinking_response = ""
        text_response = ""
        pending_tool_name: str | None = None
        pending_tool_args = None

        while True:
            async for event in response.stream_events():
                if isinstance(event, RawResponsesStreamEvent):
                    if isinstance(
                        event.data, ResponseReasoningTextDeltaEvent
                    ) or isinstance(
                            event.data, ResponseReasoningSummaryTextDeltaEvent
                    ):
                        delta = event.data.delta or ""
                        thinking_response += delta
                        yield ('thinking', delta)
                    elif isinstance(event.data, ResponseTextDeltaEvent):
                        delta = event.data.delta or ""
                        text_response += delta
                        yield ('text', delta)
                elif isinstance(event, RunItemStreamEvent):
                    if event.name == "tool_called":
                        tool_name = event.item.raw_item.name
                        tool_args = event.item.raw_item.arguments
                        pending_tool_name = tool_name
                        try:
                            pending_tool_args = json.loads(tool_args) if isinstance(tool_args, str) else tool_args
                        except (json.JSONDecodeError, TypeError):
                            pending_tool_args = {"raw": str(tool_args)}
                        yield ('tool_call', tool_name)
                    elif event.name == "tool_output":
                        # Store tool output in message history with metadata
                        output_str = event.item.output
                        if not isinstance(output_str, str):
                            output_str = str(output_str)
                        tool_msg = {
                            "role": "tool",
                            "content": output_str,
                            "_turn_id": self._turn_id,
                            "_tool_name": pending_tool_name or "unknown",
                            "_tool_args": pending_tool_args or {},
                        }
                        # Check for truncated flag in the output
                        if "[output truncated]" in output_str:
                            tool_msg["_tool_truncated"] = True
                        self.messages.append(tool_msg)
                        yield ('tool_response', output_str)
                        pending_tool_name = None
                        pending_tool_args = None

            if not response.interruptions:
                break

            state = response.to_state()

            for item in response.interruptions:
                yield ('tool_approval', (item, state))

            # Release the old response and force GC before allocating
            # the next one.  RunState objects can be large (they carry
            # full tool-output history), and the GC may not run on its
            # own between rapid tool-approval rounds.
            del response
            gc.collect()

            response = Runner.run_streamed(
                self.agent,
                state,
                max_turns=50,
            )

        # ── Store reasoning (truncated) ──────────────────────────
        if thinking_response:
            if len(thinking_response) > MAX_REASONING_CHARS:
                thinking_response = (
                    thinking_response[-MAX_REASONING_CHARS:]
                    + f"\n[... {len(thinking_response) - MAX_REASONING_CHARS} chars of earlier reasoning trimmed]"
                )
            self.messages.append({
                'id': '__fake_id__',
                'type': 'reasoning',
                'summary': [{'text': thinking_response, 'type': 'summary_text'}],
                '_turn_id': self._turn_id,
            })
            self._trim_messages()
            self._trim_by_byte_budget()

        self.add_message("assistant", text_response)

        # ── Memory diagnostic ────────────────────────────────────
        mem_mb = self._estimate_memory_mb()
        if mem_mb > 50:
            print(
                f"ⓘ [copane] Message history: {len(self.messages)} messages, "
                f"~{mem_mb:.1f} MB. Use /clear to reset.\n",
                file=sys.stderr, flush=True,
            )


# Singleton — initialized lazily to avoid setup issues on import
_agent = None


def get_agent() -> TmuxAgent:
    """Get the singleton instance of TmuxAgent."""
    global _agent
    if _agent is None:
        _agent = TmuxAgent(name="tmux-agent")
    return _agent
