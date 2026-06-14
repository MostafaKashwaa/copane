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
import os
import sys
import gc
from typing import Any, Dict

from agents import (
    Agent,
    MaxTurnsExceeded,
    RawResponsesStreamEvent,
    RunItemStreamEvent,
    RunState,
    Tool,
    Runner,
    ToolApprovalItem,
)
from openai.types.responses import (
    ResponseCompletedEvent,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseReasoningTextDeltaEvent,
    ResponseTextDeltaEvent,
)
from openai import AsyncOpenAI

from copane.tracing import traceable

from copane.tools import (
    edit_file,
    get_current_dir,
    grep_files,
    list_files,
    read_file,
    run_command,
    write_file,
    TOOL_SUMMARIZERS,
)
from copane.model_config import ModelConfig
from copane.model_provider import ModelProvider
from copane.conversation_history import ConversationHistory
from copane.log import log
from copane import session_store

MAX_TOOL_TURNS = 50  # hard cap on tool calls per response

# Thresholds for in-band nudge text appended to tool outputs.
# The model sees these as part of the tool result and can choose to
# wrap up before hitting the hard cap.
_BUDGET_NUDGE_AT = 45      # first soft warning
_BUDGET_LAST_CALL_AT = 49  # final call — demand that the model stop

# Prompt for the title-generation call (tiny, cheap, one-shot per session).
_TITLE_SYSTEM_PROMPT = """\
Write a short title (5-8 words) describing this coding task. Be specific.
Examples: "Fix N+1 query in user dashboard", "Add JWT auth to FastAPI",
"Debug race condition in task queue", "Refactor config loader to pydantic".
Reply with only the title, no quotes, no punctuation at the end."""


class TmuxAgent:
    """TmuxAgent is an AI coding assistant that runs inside a tmux pane.

    Conversation memory is managed through end-of-turn summarization:
    tool outputs are compressed to metadata stubs in-place at the end
    of each assistant response, so memory stays O(one turn), not
    O(total conversation), and the conversation shape is preserved.
    """

    def __init__(self, name):
        self.name = name
        self.history = ConversationHistory(new_turn_hook=None)
        self.agent: Agent | None = None
        self.tools: list[Tool] = [
            edit_file,
            read_file,
            run_command,
            grep_files,
            list_files,
            write_file,
            get_current_dir,
        ]
        self.model_config = ModelConfig()
        self.model_provider = ModelProvider(self.model_config)
        self._session_id: str = session_store.generate_session_id()
        self._first_user_message: str = ""   # for manifest preview
        self._title: str | None = None       # LLM-generated; None until turn 1 completes
        self._title_generated: bool = False  # gate so we only call LLM once
        self._last_saved_index: int = 0      # messages[:self._last_saved_index] already on disk

    # ── Session persistence ─────────────────────────────────────────

    @property
    def session_id(self) -> str:
        """Public read-only access to the current session id."""
        return self._session_id

    def _save_session(self):
        """Append new messages to the session JSONL file.

        Only messages added since the last save are written.
        The in-memory copy may later be trimmed — the disk file
        always retains the full conversation for ``/view``.
        Called after each assistant response, on ``/clear``, and on exit.
        """
        model = self.model_provider.get_model_info().get("name", "")
        # Clamp: in-memory trimming may have dropped messages that were
        # already persisted, leaving _last_saved_index past the end.
        if self._last_saved_index > len(self.history.messages):
            self._last_saved_index = len(self.history.messages)
        new_messages = self.history.messages[self._last_saved_index:]
        if not new_messages:
            return
        session_store.save_session(
            self._session_id,
            new_messages,
            model=model,
            title=self._title,
            first_user_message=self._first_user_message,
            input_tokens=self.history.total_input_tokens,
            output_tokens=self.history.total_output_tokens,
            append=True,
        )
        self._last_saved_index = len(self.history.messages)
        log("saved %d messages to %s (turn %d, title=%r)",
            len(new_messages), self._session_id[:19],
            self.history.turn_id, self._title)

    def save_current_session(self):
        """Public alias so app.py can trigger a save on exit/clear."""
        self._save_session()

    def _new_session_id(self):
        """Generate a fresh session id (called on /clear)."""
        self._session_id = session_store.generate_session_id()
        self._first_user_message = ""
        self._title = None
        self._title_generated = False
        self._last_saved_index = 0

    def resume_session(self, session_id: str) -> bool:
        """Save the current session, then load *session_id* into history.

        Before loading, re-summarises tool outputs and truncates
        reasoning on the raw messages so that resumed sessions don't
        carry stale full outputs or balloon in token count.  The
        conversation shape (user ↔ tool_call ↔ tool_output ↔ assistant)
        is preserved — only the output *content* is compressed.

        Returns False if the session file could not be loaded.
        """
        # Save current session first
        self._save_session()

        messages = session_store.load_session(session_id)
        if messages is None:
            log("resume_session FAILED: session not found %s", session_id[:19])
            return False

        log("resume_session %s: loaded %d messages", session_id[:19], len(messages))

        # Restore token counts from session metadata (v2) or zero (v1).
        meta = session_store.load_session_meta(session_id)
        if meta:
            self.history.total_input_tokens = meta.get("input_tokens", 0)
            self.history.total_output_tokens = meta.get("output_tokens", 0)
        else:
            self.history.total_input_tokens = 0
            self.history.total_output_tokens = 0

        # Re-compress all tool outputs in the loaded messages using the
        # same summarizers that run at end of turn.  This handles
        # sessions that were saved mid-turn (before summarization ran),
        # where raw outputs may still be present.
        self._summarize_all_tool_outputs(messages)

        # Truncate any reasoning that accumulated across turns.
        self._truncate_reasoning(messages)

        # Load into history
        self.history.clear()
        for m in messages:
            self.history.messages.append(m)

        # Restore turn_id from loaded messages
        max_turn = 0
        for m in self.history.messages:
            tid = m.get("_turn_id", 0)
            if isinstance(tid, int) and tid > max_turn:
                max_turn = tid
        self.history._turn_id = max_turn

        self.history._repair_orphaned_outputs()
        self.history._repair_orphaned_calls()

        # All messages are now on disk — nothing new to save
        self._last_saved_index = len(self.history.messages)

        # After loading full history, trim in-memory so we don't OOM
        self.history.trim_in_memory()

        # Switch to the resumed session identity
        self._session_id = session_id

        # Restore title and first_user_message from manifest (don't
        # regenerate — the title already exists from the original session)
        manifest = session_store.load_manifest()
        for entry in manifest:
            if entry.get("session_id") == session_id:
                self._first_user_message = entry.get("first_user_message", "")
                self._title = entry.get("title") or None
                break
        self._title_generated = self._title is not None

        return True

    # ── Tool output summarization ───────────────────────────────────

    @staticmethod
    def _summarize_all_tool_outputs(messages: list[dict]):
        """Compress every ``function_call_output`` in *messages* in-place.

        Runs each output through its registered tool summarizer.
        Used on resume to compact sessions that may have been saved
        before the end-of-turn summarization ran.
        """
        for m in messages:
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

    @staticmethod
    def _truncate_reasoning(messages: list[dict], max_chars: int = 400):
        """Truncate long reasoning text in-place.

        Called on resume so multi-turn sessions don't balloon from
        accumulated thinking blocks.
        """
        for m in messages:
            if m.get("type") != "reasoning":
                continue
            summary = m.get("summary", [])
            if isinstance(summary, list):
                for s in summary:
                    if isinstance(s, dict) and isinstance(s.get("text"), str):
                        text = s["text"]
                        if len(text) > max_chars:
                            s["text"] = text[:max_chars] + "..."

    def _summarize_current_turn(self):
        """Compress tool outputs from the turn that just completed.

        Called at the end of ``stream_response()`` so that session
        files always contain stubs (compact, no dead weight) and
        ``self.messages`` stays small between turns.

        Uses the same per-tool summarizers as
        ``_summarize_all_tool_outputs``, filtering on the current
        ``turn_id``.
        """
        current_turn = self.history.turn_id
        if current_turn == 0:
            return

        # Scan only from the current turn's start (O(turn_size), not O(session))
        for m in self.history.messages[self.history._current_turn_start_index:]:
            if m.get("_turn_id") != current_turn:
                continue
            if m.get("type") != "function_call_output":
                continue

            tool_name = m.get("_tool_name", "")
            summarizer = TOOL_SUMMARIZERS.get(tool_name)
            if summarizer is None:
                continue

            args = m.get("_tool_args", {})
            output = m.get("output", "")
            try:
                summary = summarizer(args, output)
            except Exception as e:
                log("summarizer FAILED for %r: %s", tool_name, e)
                continue
            if summary is not None:
                m["output"] = summary

    # ── Message helpers (thin delegators) ───────────────────────────

    def add_message(self, role: str, content: str):
        """Add a message to the conversation history."""
        self.history.add_message(role, content)

    def clear_messages(self):
        """Clear the conversation history and start a new session."""
        old_id = self._session_id
        self.history.clear()
        self._new_session_id()
        log("session cleared: %s → %s", old_id[:19], self._session_id[:19])

    def get_message_count(self) -> int:
        """Get the number of conversation rounds."""
        return self.history.get_message_count()

    def save_conversation(self, file_path: str):
        """Save the conversation history to a file."""
        self.history.save_to_file(file_path)

    def load_conversation(self, file_path: str):
        """Load the conversation history from a file."""
        self.history.load_from_file(file_path)

    # ── Model management (delegated to ModelProvider) ───────────────

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the current model."""
        return self.model_provider.get_model_info()

    def list_available_models(self) -> Dict[str, Dict[str, Any]]:
        """List all available models with their status."""
        return self.model_provider.list_available_models()

    def switch_model(self, model_key: str):
        """Switch to a different model."""
        self.model_provider.switch_model(model_key)
        self.agent = None
        log("model switched to %s", model_key)

    def setup(self):
        """Setup the agent with the selected model.

        Delegates to ``ModelProvider.create_agent`` and stores the
        returned Agent on ``self.agent``.
        """
        self.agent = self.model_provider.create_agent(
            self.tools, self.name,
        )

    # ── Tool approval ───────────────────────────────────────────────

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

    # ── Budget nudge helper ─────────────────────────────────────────

    @staticmethod
    def _budget_nudge_text(turn_count: int) -> str:
        """Return the in-band nudge string for a given tool turn.

        Appended to tool outputs so the model sees budget pressure
        naturally as part of the conversation flow.
        """
        if turn_count == _BUDGET_LAST_CALL_AT:
            return (
                f"\n\n[{turn_count} of {MAX_TOOL_TURNS} tool turns used. "
                "This is your LAST tool call. You MUST provide your "
                "answer next — do NOT call any more tools.]"
            )
        if turn_count >= _BUDGET_NUDGE_AT:
            return (
                f"\n\n[{turn_count} of {MAX_TOOL_TURNS} tool turns used. "
                "You can continue, but consider wrapping up and "
                "providing your answer soon.]"
            )
        return ""

    @dataclass
    class _StreamingContext:
        """Context for streaming responses, including partial reasoning and text."""

        thinking_response: str = ""
        text_response: str = ""
        pending_tool_calls: dict[str, tuple[str, Any]] = field(
            default_factory=dict
        )
        # Per-invocation token counts (reset at the top of each runner
        # re-creation loop in stream_response).  Flushed to
        # self.history after each complete assistant response.
        input_tokens: int = 0
        output_tokens: int = 0
        # Tool turn counter, independent of the runner lifecycle.
        # Incremented on every tool_called event.
        tool_turn_count: int = 0

    @traceable(run_type="chain", name="Stream Response")
    async def stream_response(self, user_input: str):
        """Get a response from the agent based on user input."""
        if not self.agent:
            self.setup()

        # Track first user message for the manifest preview
        if not self._first_user_message:
            self._first_user_message = user_input

        self.history.add_message("user", user_input)

        ctx = self._StreamingContext()

        response = Runner.run_streamed(
            self.agent,
            self.history.for_api(),
            max_turns=MAX_TOOL_TURNS,
        )

        while True:
            try:
                async for event in self._process_runner_events(response, ctx):
                    yield event
            except MaxTurnsExceeded:
                # Runner hit its internal turn limit — treat as
                # normal completion.  Fall through to the hard-cap
                # gate below.
                pass
            except Exception as e:
                yield ("error", f"Error processing response stream: {e}")
                self.history.repair_orphans()
                break

            # ── Handle interruptions ──────────────────────────────
            if response.interruptions:
                state = response.to_state()
                for item in response.interruptions:
                    yield ("tool_approval", (item, state))

            # ── Hard-cap gate ──────────────────────────────────────
            # Fires after the runner exits (whether from
            # MaxTurnsExceeded or natural completion).  Injects a
            # user message so the model sees an explicit instruction
            # to wrap up.
            if ctx.tool_turn_count >= MAX_TOOL_TURNS:
                log("turn budget EXHAUSTED at turn %d (session %s)",
                    ctx.tool_turn_count, self._session_id[:19])
                yield (
                    "turn_budget_exhausted",
                    ctx.tool_turn_count,
                )
                self.history.add_message(
                    "user",
                    "You have reached the maximum number of tool calls. "
                    "Please stop calling tools and provide your answer now. "
                    "Summarize what you have found and ask the user to "
                    "continue if needed.",
                )
                ctx.tool_turn_count = 0
                response = Runner.run_streamed(
                    self.agent,
                    self.history.for_api(),
                    max_turns=3,
                )
                continue

            # ── Exit or continue ──────────────────────────────────
            if not response.interruptions:
                break

            response = self._recreate_runner(response, state)

        # Flush per-invocation token counts to session-level totals.
        self.history.total_input_tokens += ctx.input_tokens
        self.history.total_output_tokens += ctx.output_tokens

        self._store_reasoning(ctx.thinking_response)
        self.history.add_message("assistant", ctx.text_response)

        # Generate a title from the first user+assistant exchange.
        # This is a cheap one-shot LLM call (~10 output tokens) that
        # only fires on turn 1.  Fail silently — the title is a nice-to-have.
        # if self.history.turn_id == 1 and not self._title_generated:
        if not self._title_generated:
            try:
                self._title = await self._generate_title(
                    self._first_user_message,
                    ctx.text_response,
                )
                log("title generated for %s: %r", self._session_id[:19], self._title)
            except Exception as e:
                log("title generation FAILED for %s: %s", self._session_id[:19], e)
            finally:
                self._title_generated = True

        # Summarize the turn that just completed so session files
        # always contain stubs, not full tool outputs.
        self._summarize_current_turn()

        self._save_session()      # append current turn to disk (full history preserved)
        self.history.trim_in_memory()  # drop oldest if byte budget exceeded (OOM safety)
        self._print_memory_warning()

    # ── Title generation ────────────────────────────────────────────

    async def _generate_title(
        self, user_msg: str, assistant_msg: str
    ) -> str:
        """Ask the current model to produce a short, specific title.

        Sends a single chat-completion request with the user's first
        message and the assistant's first response (each truncated to
        500 chars so we don't waste tokens on long code blocks).
        Returns a cleaned-up title string.
        """
        # Build client from the same model config the agent is using
        info = self.model_provider.get_model_info()
        model_name = info.get("name", "")
        base_url = info.get("base_url", "")
        env_key = info.get("env_key", "")
        api_key = os.getenv(env_key, "") if env_key else ""

        client = AsyncOpenAI(base_url=base_url, api_key=api_key)

        # Truncate inputs so the call stays tiny
        user_snippet = user_msg[:500]
        assistant_snippet = assistant_msg[:500]

        resp = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": _TITLE_SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"User asked: {user_snippet}\n\n"
                    f"Assistant responded: {assistant_snippet}"
                )},
            ],
            max_tokens=30,
            temperature=0.3,
        )

        title = resp.choices[0].message.content or ""
        # Strip common wrapping/quoting
        title = title.strip().strip('"\'').rstrip(".")
        return title

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
    ) -> tuple[str, Any] | None:
        """Handle a single raw event from the response stream.

        Yields ``("thinking", delta)`` for reasoning text,
        ``("text", delta)`` for response text, and
        ``("usage", {...})`` when the response completes with token
        counts reported by the API.

        Token counts are also accumulated into *context* so that
        ``stream_response()`` can flush them to the session-level
        history totals after each complete assistant response.
        """
        if isinstance(
                event.data, (ResponseReasoningTextDeltaEvent, ResponseReasoningSummaryTextDeltaEvent)):
            delta = event.data.delta or ""
            context.thinking_response += delta
            return ("thinking", delta)
        elif isinstance(event.data, ResponseTextDeltaEvent):
            delta = event.data.delta or ""
            context.text_response += delta
            return ("text", delta)
        elif isinstance(event.data, ResponseCompletedEvent):
            usage = event.data.response.usage
            if usage is not None:
                context.input_tokens += usage.input_tokens
                context.output_tokens += usage.output_tokens
                return ("usage", {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "total_tokens": usage.total_tokens,
                })
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

                ctx.tool_turn_count += 1

                self.history.add_tool_call(tool_call_id, tool_name, tool_args)
                ctx.pending_tool_calls[tool_call_id] = (tool_name, tool_args)

                # Prevent orphaned tool_calls: if the model hallucinates a
                # non-existent tool name, add a synthetic error tool output
                # with the same call_id so the tool_output handler can still
                # correlate it and avoid leaving a dangling pending_tool_call.
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
                return ("tool_call", (tool_name, tool_call_id))

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

                # ── In-band budget nudge ──────────────────────────
                # Append to the history copy so the model sees the
                # budget pressure as part of the result.  The UI still
                # receives the original object (event.item.output) for
                # proper SUCCESS / ERROR colouring.
                history_output = output_str + self._budget_nudge_text(
                    ctx.tool_turn_count
                )

                self.history.add_tool_output(
                    tool_call_id or "",
                    history_output,
                    tool_name or "unknown",
                    tool_args_parsed or {},
                )
                return ("tool_response", (event.item.output, tool_call_id))
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


def get_agent(name: str = "copane") -> TmuxAgent:
    """Return the singleton TmuxAgent, creating it on first call."""
    global _agent
    if _agent is None:
        _agent = TmuxAgent(name)
    return _agent
