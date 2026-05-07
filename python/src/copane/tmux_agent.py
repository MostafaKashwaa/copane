#!/usr/bin/env python3
"""
tmux-agent: AI agent configuration for terminal-based coding assistance.
Enhanced with professional model selection and configuration management.

Conversation memory is managed through turn-boundary summarization:
tool outputs from the previous turn are compressed to metadata stubs
in-place (path, line count, purpose hint for file reads; exit code +
preview for commands; etc.) so memory stays O(one turn) and the
conversation shape is preserved.
"""

from dataclasses import dataclass, field
import json
import logging
import os
import sys
import gc
import time
from pathlib import Path
from typing import Any, Dict

from agents import (
    Agent,
    OpenAIChatCompletionsModel,
    RawResponsesStreamEvent,
    RunItemStreamEvent,
    RunState,
    Tool,
    Runner,
    ToolApprovalItem,
)
from openai import AsyncOpenAI
from openai.types.responses import (
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseReasoningTextDeltaEvent,
    ResponseTextDeltaEvent,
)

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
from copane.model_config import ModelConfig
from copane.conversation_history import ConversationHistory

# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s [%(levelname)s] %(message)s",
#     handlers=[
#         logging.FileHandler("tmux_agent.log"),
#         logging.StreamHandler(sys.stdout)
#     ]
# )

MAX_TOOL_TURNS = 50  # max turns for a single tool-using response


class TmuxAgent:
    """TmuxAgent is an AI coding assistant that runs inside a tmux pane.

    Conversation memory is managed through turn-boundary summarization:
    tool outputs are compressed to metadata stubs in-place so memory
    stays O(one turn), not O(total conversation), and the conversation
    shape is preserved.
    """

    def __init__(self, name):
        self.name = name
        self.history = ConversationHistory(
            new_turn_hook=self._summarize_previous_turn
        )
        self.agent: Agent | None = None
        self.tools: list[Tool] = [
            read_file,
            run_command,
            grep_files,
            list_files,
            write_file,
            get_current_dir,
        ]
        self.model_config = ModelConfig()

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
            # with open(path, "w") as f:
            # json.dump(self.history.messages, f, indent=2, default=str)
            self.history.save_to_file(str(path))
        except (TypeError, OSError) as e:
            logging.warning("\nFailed to save full history: %s", e)

    # ── Turn-boundary summarization ─────────────────────────────────

    def _summarize_previous_turn(self, messages: list[dict], prev_turn_id: int):
        """Compress tool outputs from the previous turn into metadata stubs.

        Called by ``ConversationHistory.add_message()`` at user-message
        boundaries, *before* the turn id is incremented.  Saves full
        history to disk first, then replaces each tool-output message's
        ``output`` field in-place with its summarised stub.  Nothing is
        removed or moved — the conversation shape is preserved.
        """
        if prev_turn_id == 0:
            return  # first turn — nothing to summarize

        # Save full history before modifying it
        self._save_full_history()

        for m in messages:
            if m.get("_turn_id") != prev_turn_id:
                continue
            if m.get("type") != "function_call_output":
                continue

            tool_name = m.get("_tool_name", "")
            summarizer = TOOL_SUMMARIZERS.get(tool_name)
            if summarizer is None:
                continue

            args = m.get("_tool_args", {})
            output = m.get("output", "")
            summary = summarizer(args, output)
            if summary is not None:
                m["output"] = summary

    # ── Message helpers (thin delegators) ───────────────────────────

    def add_message(self, role: str, content: str):
        """Add a message to the conversation history."""
        self.history.add_message(role, content)

    def clear_messages(self):
        """Clear the conversation history."""
        self.history.clear()

    def get_message_count(self) -> int:
        """Get the number of conversation rounds."""
        return self.history.get_message_count()

    def save_conversation(self, file_path: str):
        """Save the conversation history to a file."""
        self.history.save_to_file(file_path)

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
            "status": self._check_model_status(model_info),
        }

    def _check_model_status(self, model_info: Dict[str, Any]) -> str:
        """Check the availability status of a model."""
        env_key = model_info.get("env_key", "")

        if model_info.get("type") == "local":
            ollama_url = model_info.get("base_url")
            if ollama_url:
                try:
                    import httpx

                    response = httpx.get(ollama_url + "/models", timeout=2)
                    if response.status_code == 200:
                        return "available"
                    else:
                        return "unreachable (try running 'ollama serve' or correcting base_url)"
                except ImportError:
                    return "Cannot check (httpx not installed)"
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
                "is_selected": key == self.model_config.get_selected_model(),
            }

        return result

    def switch_model(self, model_key: str):
        """Switch to a different model."""
        models = self.model_config.get_available_models()
        if model_key not in models:
            raise ValueError(
                f"Model '{model_key}' not found. Available models: {list(models.keys())}"
            )

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
                f"Model configuration for '{selected_key}' not found"
            )

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

Between turns, tool outputs are compressed to metadata stubs in-place
(path, line count, purpose hint for file reads; exit code + preview
for commands; etc.). Exact file contents are NOT retained across turns.
The conversation shape is preserved — you see every tool call and its
summarized result in the original order.

- Gather all needed information from files within the current turn.
- At the start of a new turn, re-read key files if exact content is
  needed (one read_file call per file gets full contents).
- Use grep_files first to locate relevant sections, then read_file
  with start_line/end_line to zoom in.
""",
            tools=self.tools,
            model=model,
        )

    def handle_tool_approval(
        self, item: ToolApprovalItem, decision: str, state: RunState
    ):
        """Approve or reject a tool call."""
        match decision:
            case "y":
                state.approve(item)
            case "n":
                state.reject(
                    item,
                    rejection_message="User rejected this tool call. If you can't proceed without this tool call, stop trying and ask the user how to proceed.",
                )
            case "a":
                state.approve(item, always_approve=True)
            case "r":
                state.reject(
                    item,
                    always_reject=True,
                    rejection_message="User requested retry with modifications. Try a different approach.",
                )
            case "q":
                raise RuntimeError(
                    "Tool approval process interrupted by user.")
            case _:
                raise ValueError(
                    f"Invalid decision: {decision}. Must be one of 'y', 'n', 'a', 'r', or 'q'."
                )

    @dataclass
    class _StreamingContext:
        """Context for streaming responses, including partial reasoning and text."""

        thinking_response: str = ""
        text_response: str = ""
        pending_tool_calls: dict[str, tuple[str, Any]] = field(
            default_factory=dict
        )

    @traceable(run_type="chain", name="Stream Response")
    async def stream_response(self, user_input: str):
        """Get a response from the agent based on user input."""
        if not self.agent:
            self.setup()

        self.history.add_message("user", user_input)

        response = Runner.run_streamed(
            self.agent,
            self.history.for_api(),
            max_turns=MAX_TOOL_TURNS,
        )

        ctx = self._StreamingContext()

        while True:
            async for event in self._process_runner_events(response, ctx):
                yield event

            if not response.interruptions:
                break

            state = response.to_state()

            for item in response.interruptions:
                yield ("tool_approval", (item, state))

            response = self._recreate_runner(response, state)

        self._store_reasoning(ctx.thinking_response)
        self.history.add_message("assistant", ctx.text_response)
        self._print_memory_warning()

    # ──────────────────── Event processing ─────────────────────────────────
    async def _process_runner_events(self, response, ctx: _StreamingContext):
        """Process events from the Runner, yielding tool approvals as needed."""
        async for event in response.stream_events():
            if isinstance(event, RawResponsesStreamEvent):
                result = self._handle_raw_event(event, ctx)
                if result is not None:
                    yield result
            elif isinstance(event, RunItemStreamEvent):
                result = self._handle_run_item_event(event, ctx)
                if result is not None:
                    yield result

    # ──────────────────── Event handlers ─────────────────────────────────
    def _handle_raw_event(
        self, event: RawResponsesStreamEvent, context: _StreamingContext
    ) -> tuple[str, str] | None:
        """Handle a single raw event from the response stream."""
        if isinstance(
                event.data, (ResponseReasoningTextDeltaEvent, ResponseReasoningSummaryTextDeltaEvent)):
            delta = event.data.delta or ""
            context.thinking_response += delta
            return ("thinking", delta)
        elif isinstance(event.data, ResponseTextDeltaEvent):
            delta = event.data.delta or ""
            context.text_response += delta
            return ("text", delta)
        return None

    def _handle_run_item_event(
        self, event: RunItemStreamEvent, ctx: _StreamingContext
    ) -> tuple[str, Any] | None:
        """Handle a single run item event from the response stream."""
        match event.name:
            case "tool_called":
                tool_call_id = event.item.raw_item.call_id
                tool_name = event.item.raw_item.name
                tool_args = event.item.raw_item.arguments

                self.history.add_tool_call(tool_call_id, tool_name, tool_args)
                ctx.pending_tool_calls[tool_call_id] = (tool_name, tool_args)

                # Prevent orphaned tool_calls: if the models hallucinates a non-existent tool name,
                # add a synthetic error tool output with the same call_id, so the tool_output handler
                # can still correlate it and avoid leaving a dangling pending_tool_call entry.
                if tool_name not in [t.name for t in self.tools]:
                    try:
                        tool_args_parsed = (json.loads(tool_args)
                                            if isinstance(tool_args, str)
                                            else tool_args
                                            )
                    except (json.JSONDecodeError, TypeError):
                        tool_args_parsed = {"raw": str(tool_args)}

                    self.history.add_tool_output(
                        tool_call_id,
                        f"Error: attempted to call unknown tool '{tool_name}'. Available tools: {[t.name for t in self.tools]}",
                        tool_name,
                        tool_args_parsed or {},
                    )
                    # ctx.pending_tool_calls.pop(tool_call_id, None)
                return ("tool_call", tool_name)

            case "tool_output":
                # Intentionally cross-reference call_id via pending_tool_calls.
                #
                # The SDK gives us different raw_item types for the two events:
                #   "tool_called" → ToolCallItem      → raw_item is a Pydantic model
                #                   (ResponseFunctionToolCall) → use .call_id / .name / .arguments
                #   "tool_output" → ToolCallOutputItem → raw_item is a TypedDict
                #                   (FunctionCallOutput)      → use ["call_id"] / ["output"]
                #
                # Both are valid SDK types — this is not a bug, it's the framework's design.
                # We deliberately store (name, args) in ctx.pending_tool_calls during the
                # "tool_called" handler and look them up here by call_id, because the
                # tool_output raw_item does not carry name/arguments. The isinstance(…, dict)
                # guard is purely defensive: FunctionCallOutput is always dict-shaped.

                output_str = event.item.output
                if not isinstance(output_str, str):
                    output_str = str(output_str)

                tool_call_id = (
                    event.item.raw_item.get("call_id")
                    if isinstance(event.item.raw_item, dict)
                    else None
                )
                tool_name = (
                    ctx.pending_tool_calls.get(tool_call_id, (None, None))[0]
                    if tool_call_id
                    else None
                )
                tool_args = (
                    ctx.pending_tool_calls.get(tool_call_id, (None, None))[1]
                    if tool_call_id
                    else None
                )

                try:
                    tool_args_parsed = (
                        json.loads(tool_args)
                        if isinstance(tool_args, str)
                        else tool_args
                    )
                except (json.JSONDecodeError, TypeError):
                    tool_args_parsed = {"raw": str(tool_args)}

                self.history.add_tool_output(
                    tool_call_id or "",
                    output_str,
                    tool_name or "unknown",
                    tool_args_parsed or {},
                )
                return ("tool_response", event.item.output)
        return None

    # ──────────────────── Post-response processing ─────────────────────────
    def _store_reasoning(self, reasoning: str):
        """Store reasoning text in the conversation history."""
        self.history.add_reasoning(reasoning)

    def _print_memory_warning(self):
        """Print a warning to stderr if message history exceeds threshold."""
        mem_mb = self.history.estimate_memory_mb()
        if mem_mb > 50:
            print(
                f"ⓘ [copane] Message history: {len(self.history.messages)} messages, "
                f"~{mem_mb:.1f} MB. Use /clear to reset.\n",
                file=sys.stderr,
                flush=True,
            )

    # ──────────────────── Runner recreation ────────────────────────────────
    def _recreate_runner(self, response, state):
        """Recreate a Runner from the current response state after tool approval."""
        # Release the old response and force GC before allocating
        # the next one.  RunState objects can be large (they carry
        # full tool-output history), and the GC may not run on its
        # own between rapid tool-approval rounds.
        del response
        gc.collect()
        return Runner.run_streamed(
            self.agent,
            state,
            max_turns=MAX_TOOL_TURNS,
        )


# Singleton — initialized lazily to avoid setup issues on import
_agent = None


def get_agent() -> TmuxAgent:
    """Get the singleton instance of TmuxAgent."""
    global _agent
    if _agent is None:
        _agent = TmuxAgent(name="tmux-agent")
    return _agent
