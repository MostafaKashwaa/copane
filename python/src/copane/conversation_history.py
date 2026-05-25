"""Conversation history management for copane.

``ConversationHistory`` owns the message list and all memory-management
logic: turn-boundary hooks, trimming (by count and byte budget), orphan
repair, reasoning truncation, and persistence helpers.

It is deliberately **SDK-aware** but **tool-implementation-agnostic** — 
turn-boundary summarization is injected via a ``new_turn_hook`` callable set by the agent.
"""

import logging
import sys
from typing import Callable

# ---------------------------------------------------------------------------
# Memory safety limits
# ---------------------------------------------------------------------------

# Hard message-count cap - only user and assistant messages are counted.
# Each turn adds exactly 2 messages (user + assistant). Tool calls/outputs 
# and reasoning are ignored because turn-boundary summarization compresses
# them to ~200-byte stubs that don't meaningfully affect memory or tokens.
MAX_MESSAGES = 60

# When we exceed MAX_MESSAGES we trim back to this fraction of MAX
# so we don't trim on every single add_message call.
TRIM_TARGET_FRACTION = 0.67  # keeps 40 messages (20 turns) when we hit 60.

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

# Internal metadata fields that must be stripped before sending
# messages to the model API.  The SDK's chatcmpl_converter handles
# both ``EasyInputMessageParam`` (``{"role", "content"}``) and
# ``FunctionCallOutput`` (``{"type", "call_id", "output"}``) —
# neither tolerates extra keys.
_INTERNAL_FIELDS = frozenset(
    {
        "_turn_id",
        "_tool_name",
        "_tool_args",
        "_tool_truncated",
    }
)

# Signature for the new-turn hook: receives the message list and the
# current (pre-increment) turn id, mutates messages in-place.
NewTurnHook = Callable[[list[dict], int], None]


class ConversationHistory:
    """Owns the message list and all memory-safety logic.

    Parameters
    ----------
    new_turn_hook:
        Called when ``add_message("user", ...)`` is invoked, *before*
        the turn id is incremented.  Receives ``(messages, turn_id)``.
        The agent uses this to inject turn-boundary summarization.
    """

    def __init__(self, new_turn_hook: NewTurnHook | None = None):
        self.messages: list[dict] = []
        self._turn_id: int = 0
        self._trim_warned: bool = False
        self._new_turn_hook = new_turn_hook

        # Session-level token accumulation (across all turns).
        # Updated by TmuxAgent.stream_response() after each complete
        # assistant response, using the usage reported by the API.
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0

    # ── public API ──────────────────────────────────────────────────

    @property
    def turn_id(self) -> int:
        """Current turn id (incremented on each user message)."""
        return self._turn_id

    def add_message(self, role: str, content: str) -> None:
        """Add a user or assistant message.

        At user-message boundaries (turn boundaries), the new-turn hook
        is invoked to summarise the previous turn's tool outputs.
        """
        if role == "user":
            if self._new_turn_hook is not None:
                self._new_turn_hook(self.messages, self._turn_id)
            self._turn_id += 1

        msg: dict = {"role": role, "content": content,
                     "_turn_id": self._turn_id}
        self.messages.append(msg)
        self._trim_messages()
        self._trim_by_byte_budget()

    def add_tool_call(self, call_id: str, name: str, arguments: str) -> None:
        """Record a ``function_call`` event in the message history."""
        self.messages.append(
            {
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
                "_turn_id": self._turn_id,
            }
        )

    def add_tool_output(
        self,
        call_id: str,
        output: str,
        tool_name: str,
        tool_args: dict,
    ) -> None:
        """Record a ``function_call_output`` event in the message history."""
        msg: dict = {
            "type": "function_call_output",
            "call_id": call_id,
            "output": output,
            "_turn_id": self._turn_id,
            "_tool_name": tool_name,
            "_tool_args": tool_args,
        }
        if "[output truncated]" in output:
            msg["_tool_truncated"] = True
        self.messages.append(msg)

    def add_reasoning(self, reasoning: str) -> None:
        """Store reasoning/chain-of-thought text, truncating if needed."""
        if not reasoning:
            return
        if len(reasoning) > MAX_REASONING_CHARS:
            reasoning = (
                reasoning[-MAX_REASONING_CHARS:]
                + f"\n[... {len(reasoning) - MAX_REASONING_CHARS} chars of earlier reasoning trimmed]"
            )
        self.messages.append(
            {
                "id": "__fake_id__",
                "type": "reasoning",
                "summary": [{"text": reasoning, "type": "summary_text"}],
                "_turn_id": self._turn_id,
            }
        )
        self._trim_messages()
        self._trim_by_byte_budget()

    def clear(self) -> None:
        """Reset the conversation to empty."""
        self.messages = []
        self._trim_warned = False
        self._turn_id = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def get_message_count(self) -> int:
        """Count user + assistant turn-pairs (rounds), ignoring reasoning."""
        return sum(
            1 for m in self.messages if m.get("role") in ("user", "assistant")
        ) // 2

    def save_to_file(self, file_path: str) -> None:
        """Write the message list to a JSON file."""
        import json

        with open(file_path, "w") as f:
            json.dump(self.messages, f, indent=2, default=str)

    def load_from_file(self, file_path: str) -> None:
        """Load the message list from a JSON file, replacing current history.

        Restores ``_turn_id`` from the highest ``_turn_id`` found in the
        loaded messages, and runs orphan repair in both directions so the
        result is safe to pass to ``for_api()``.
        """
        import json

        with open(file_path) as f:
            self.messages = json.load(f)

        # Restore turn id from the highest _turn_id in the loaded messages
        max_turn = 0
        for m in self.messages:
            tid = m.get("_turn_id", 0)
            if isinstance(tid, int) and tid > max_turn:
                max_turn = tid
        self._turn_id = max_turn

        self._repair_orphaned_outputs()
        self._repair_orphaned_calls()

    def repair_orphans(self) -> None:
        """Public entry point: repair orphans in both directions.

        Safe to call at any time (e.g. after a streaming error that may
        have left a ``function_call`` without its matching output).
        """
        self._repair_orphaned_outputs()
        self._repair_orphaned_calls()

    def estimate_memory_mb(self) -> float:
        """Rough estimate of memory used by the message list (MB)."""
        return self._estimate_total_bytes() / (1024 * 1024)

    def for_api(self) -> list[dict]:
        """Return a shallow copy of messages with internal fields stripped.

        The OpenAI Agents SDK chat completion converter handles both
        ``EasyInputMessageParam`` (``{"role", "content"}``) and
        ``FunctionCallOutput`` (``{"type", "call_id", "output"}``) —
        neither tolerates extra keys.  This method produces clean dicts
        safe for the model API while keeping the internal fields on
        ``self.messages`` for turn-boundary summarization.
        """
        return [
            {k: v for k, v in m.items() if k not in _INTERNAL_FIELDS}
            for m in self.messages
        ]

    # ── internals ───────────────────────────────────────────────────

    def _estimate_total_bytes(self) -> int:
        """Estimate the total byte size of the full message history."""
        try:
            total = 0
            for m in self.messages:
                total += len(str(m))
            return total
        except (TypeError, AttributeError, KeyError):
            return 0

    def _repair_orphaned_outputs(self) -> None:
        """Remove ``function_call_output`` messages whose matching
        ``function_call`` is missing.

        After trimming old messages (either by count or byte budget),
        it is possible that a ``function_call_output`` survives but its
        corresponding ``function_call`` was dropped.  The OpenAI Agents
        SDK requires every ``function_call_output`` to be preceded by a
        ``function_call`` with the same ``call_id`` — an orphaned output
        causes a hard error.
        """
        valid_call_ids: set[str] = set()
        for m in self.messages:
            if m.get("type") == "function_call":
                cid = m.get("call_id")
                if cid:
                    valid_call_ids.add(cid)

        before = len(self.messages)
        self.messages = [
            m
            for m in self.messages
            if m.get("type") != "function_call_output"
            or m.get("call_id") in valid_call_ids
        ]
        removed = before - len(self.messages)
        if removed:
            logging.warning(
                "\nOrphan repair: removed %d function_call_output(s) with no "
                "matching function_call.",
                removed,
            )

    def _repair_orphaned_calls(self) -> None:
        """Remove ``function_call`` messages whose matching
        ``function_call_output`` is missing.

        This is the reverse of ``_repair_orphaned_outputs``.  It handles
        the case where a streaming error leaves a ``function_call`` in
        history before its corresponding ``function_call_output`` could
        be recorded.  Such orphaned calls cause the API to reject the
        next request because tool calls must be followed by tool messages.
        """
        valid_output_ids: set[str] = set()
        for m in self.messages:
            if m.get("type") == "function_call_output":
                cid = m.get("call_id")
                if cid:
                    valid_output_ids.add(cid)

        before = len(self.messages)
        self.messages = [
            m
            for m in self.messages
            if m.get("type") != "function_call"
            or m.get("call_id") in valid_output_ids
        ]
        removed = before - len(self.messages)
        if removed:
            logging.warning(
                "\nOrphan repair: removed %d function_call(s) with no "
                "matching function_call_output.",
                removed,
            )

    def _trim_messages(self) -> None:
        """Trim old messages when user+assistant count exceeds MAX_MESSAGES.

        Only user and assistant messages count towards the cap — 
        tool calls/outputs and reasoning are ignored because turn-boundary summarization 
        compresses them to ~200-byte stubs that don't meaningfully affect memory or tokens.
        Trims back to TRIM_TARGET_FRACTION of MAX_MESSAGES to avoid trimming on every 
        single add_message call once the cap is hit.
        """
        conversation_count = sum(
            1 for m in self.messages if m.get("role") in ("user", "assistant")
        ) 
        if conversation_count <= MAX_MESSAGES:
            return

        if not self._trim_warned:
            print(
                f"\n⚠ [copane] Message history full "
                f"({conversation_count} user+assistant messages). "
                f"{len(self.messages) - conversation_count} tool/reasoning messages are not counted in the cap. "
                f"Trimming oldest messages to conserve memory. "
                f"Use /clear to reset.\n",
                file=sys.stderr,
                flush=True,
            )
            self._trim_warned = True

        target = int(MAX_MESSAGES * TRIM_TARGET_FRACTION)
        # Pop from the front until user+assistant count is at or below target
        # Orphan repair after the loop cleans up any dangling tool calls/outputs.
        while True:
            n = sum(1 for m in self.messages if m.get("role") in ("user", "assistant"))
            if n <= target or not self.messages:
                break
            self.messages.pop(0)
        self._repair_orphaned_outputs()

    def _trim_by_byte_budget(self) -> None:
        """Aggressively trim old messages when the byte budget is exceeded.

        Keeps the most recent KEEP_RECENT_MESSAGES and drops everything
        older.  This is a last-resort safety valve — normal trimming
        happens via ``_trim_messages`` (message-count based).
        """
        total = self._estimate_total_bytes()
        if total <= MAX_HISTORY_BYTES:
            return

        if not self._trim_warned:
            print(
                f"\n⚠ [copane] Message history too large (~{total / 1_000_000:.1f} MB). "
                f"Trimming oldest messages to prevent OOM. "
                f"Use /clear to reset.\n",
                file=sys.stderr,
                flush=True,
            )
            self._trim_warned = True

        keep = min(KEEP_RECENT_MESSAGES, len(self.messages))
        dropped = len(self.messages) - keep
        self.messages = self.messages[-keep:] if keep else []
        self._repair_orphaned_outputs()
        logging.warning(
            "Byte-budget trim: dropped %d messages, kept %d (~%d KB now)",
            dropped,
            keep,
            self._estimate_total_bytes() // 1024,
        )
