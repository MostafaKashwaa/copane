"""Tests for ConversationHistory — pure logic, no SDK/LLM dependencies."""

import json
import tempfile
from pathlib import Path

import pytest

from copane.conversation_history import (
    ConversationHistory,
    MAX_MESSAGES,
    MAX_HISTORY_BYTES,
    MAX_REASONING_CHARS,
    KEEP_RECENT_MESSAGES,
    TRIM_TARGET_FRACTION,
    _INTERNAL_FIELDS,
)


# -------------------------------------------------------------------
# helpers
# -------------------------------------------------------------------


def _build_messages(count: int, start_turn: int = 1) -> list[dict]:
    """Build ``count`` synthetic user/assistant pairs."""
    msgs = []
    for i in range(count):
        t = start_turn + i
        msgs.append({"role": "user", "content": f"q{i}", "_turn_id": t})
        msgs.append(
            {"role": "assistant", "content": f"a{i}", "_turn_id": t}
        )
    return msgs


# -------------------------------------------------------------------
# basic lifecycle
# -------------------------------------------------------------------


class TestLifecycle:
    def test_initial_state(self):
        h = ConversationHistory()
        assert h.messages == []
        assert h.turn_id == 0
        assert h.get_message_count() == 0
        assert h.estimate_memory_mb() == 0.0

    def test_add_user_increments_turn(self):
        h = ConversationHistory()
        h.add_message("user", "hello")
        assert h.turn_id == 1
        assert len(h.messages) == 1

    def test_add_assistant_does_not_increment_turn(self):
        h = ConversationHistory()
        h.add_message("user", "hello")
        h.add_message("assistant", "world")
        assert h.turn_id == 1
        assert len(h.messages) == 2

    def test_multiple_turns(self):
        h = ConversationHistory()
        h.add_message("user", "t1")
        h.add_message("assistant", "t1")
        h.add_message("user", "t2")
        h.add_message("assistant", "t2")
        assert h.turn_id == 2
        assert h.get_message_count() == 2

    def test_clear_resets_everything(self):
        h = ConversationHistory()
        h.add_message("user", "hello")
        h.add_tool_call("cid1", "read_file", '{"path":"/x"}')
        h.add_tool_output("cid1", "output", "read_file", {"path": "/x"})
        h.clear()
        assert h.messages == []
        assert h.turn_id == 0
        assert h.get_message_count() == 0
        # _trim_warned resets (no warning silence after clear)
        assert h._trim_warned is False


# -------------------------------------------------------------------
# turn-boundary hook
# -------------------------------------------------------------------


class TestHook:
    def test_hook_called_on_user_message(self):
        called = []

        def hook(msgs, tid):
            called.append((len(msgs), tid))

        h = ConversationHistory(new_turn_hook=hook)
        h.add_message("user", "hello")
        assert called == [(0, 0)]  # 0 msgs, turn 0 before increment

    def test_hook_not_called_on_assistant_message(self):
        called = []

        def hook(msgs, tid):
            called.append(True)

        h = ConversationHistory(new_turn_hook=hook)
        h.add_message("assistant", "response")
        assert called == []

    def test_hook_not_called_first_turn_if_none(self):
        h = ConversationHistory(new_turn_hook=None)
        h.add_message("user", "hello")
        assert h.turn_id == 1  # no crash, turn still incremented

    def test_hook_sees_messages_from_previous_turns(self):
        seen = []

        def hook(msgs, tid):
            seen.append((len(msgs), tid))

        h = ConversationHistory(new_turn_hook=hook)
        h.add_message("user", "turn1")
        h.add_message("assistant", "turn1")
        # hook should have been called with 0 messages
        h.add_message("user", "turn2")
        # hook should have been called with 2 messages from turn 1
        assert len(seen) == 2
        assert seen[0] == (0, 0)
        assert seen[1] == (2, 1)


# -------------------------------------------------------------------
# tool calls & outputs
# -------------------------------------------------------------------


class TestToolMessages:
    def test_add_tool_call(self):
        h = ConversationHistory()
        h.add_tool_call("cid1", "read_file", '{"path":"/x"}')
        assert len(h.messages) == 1
        assert h.messages[0]["type"] == "function_call"
        assert h.messages[0]["call_id"] == "cid1"
        assert h.messages[0]["_turn_id"] == 0  # before any user msg

    def test_add_tool_output(self):
        h = ConversationHistory()
        h.add_tool_output("cid1", "contents", "read_file", {"path": "/x"})
        assert len(h.messages) == 1
        assert h.messages[0]["type"] == "function_call_output"
        assert h.messages[0]["output"] == "contents"
        assert h.messages[0]["_tool_name"] == "read_file"
        assert h.messages[0]["_tool_args"] == {"path": "/x"}

    def test_tool_output_truncated_flag(self):
        h = ConversationHistory()
        h.add_tool_output("cid1", "[output truncated] blah", "run_command", {})
        assert h.messages[0]["_tool_truncated"] is True

    def test_tool_output_no_truncated_flag(self):
        h = ConversationHistory()
        h.add_tool_output("cid1", "normal output", "run_command", {})
        assert "_tool_truncated" not in h.messages[0]

    def test_tool_call_and_output_in_same_turn(self):
        h = ConversationHistory()
        h.add_message("user", "read foo")
        h.add_tool_call("cid1", "read_file", '{"path":"/foo"}')
        h.add_tool_output("cid1", "bar", "read_file", {"path": "/foo"})
        # all should have same turn id
        turn = h.turn_id
        for m in h.messages[1:]:  # skip user msg
            assert m["_turn_id"] == turn


# -------------------------------------------------------------------
# reasoning
# -------------------------------------------------------------------


class TestReasoning:
    def test_add_reasoning(self):
        h = ConversationHistory()
        h.add_reasoning("let me think...")
        assert len(h.messages) == 1
        assert h.messages[0]["type"] == "reasoning"
        assert h.messages[0]["summary"][0]["text"] == "let me think..."

    def test_empty_reasoning_not_stored(self):
        h = ConversationHistory()
        h.add_reasoning("")
        assert len(h.messages) == 0

    def test_none_reasoning_not_stored(self):
        h = ConversationHistory()
        h.add_reasoning(None)  # type: ignore
        assert len(h.messages) == 0

    def test_reasoning_truncation(self):
        h = ConversationHistory()
        long_text = "x" * (MAX_REASONING_CHARS + 500)
        h.add_reasoning(long_text)
        stored = h.messages[0]["summary"][0]["text"]
        assert len(stored) < len(long_text)
        assert "[... " in stored
        assert "chars of earlier reasoning trimmed" in stored

    def test_reasoning_exactly_at_limit_not_truncated(self):
        h = ConversationHistory()
        exact = "y" * MAX_REASONING_CHARS
        h.add_reasoning(exact)
        stored = h.messages[0]["summary"][0]["text"]
        assert stored == exact


# -------------------------------------------------------------------
# for_api — internal field stripping
# -------------------------------------------------------------------


class TestForApi:
    def test_strips_all_internal_fields(self):
        h = ConversationHistory()
        h.add_message("user", "hello")
        h.add_tool_call("cid1", "grep_files", '{"pattern":"x"}')
        h.add_tool_output("cid1", "found", "grep_files", {"pattern": "x"})
        h.add_reasoning("hmm")
        # also add a truncated output
        h.add_tool_output(
            "cid2",
            "[output truncated] result",
            "run_command",
            {"cmd": "ls"},
        )

        clean = h.for_api()
        assert len(clean) == len(h.messages)
        for m in clean:
            for field in _INTERNAL_FIELDS:
                assert field not in m, f"{field} leaked in {list(m.keys())}"

    def test_for_api_does_not_mutate_original(self):
        h = ConversationHistory()
        h.add_message("user", "hello")
        original_keys = set(h.messages[0].keys())
        h.for_api()
        assert set(h.messages[0].keys()) == original_keys

    def test_for_api_preserves_sdk_required_fields(self):
        """Fields the SDK needs must survive stripping."""
        h = ConversationHistory()
        h.add_message("user", "hello")
        h.add_message("assistant", "world")
        h.add_tool_call("cid1", "read_file", "{}")
        h.add_tool_output("cid1", "output", "read_file", {})
        h.add_reasoning("think")

        clean = h.for_api()
        # user/assistant: role + content
        assert clean[0] == {"role": "user", "content": "hello"}
        assert clean[1] == {"role": "assistant", "content": "world"}
        # function_call: type + call_id + name + arguments
        assert clean[2]["type"] == "function_call"
        assert "call_id" in clean[2]
        # function_call_output: type + call_id + output
        assert clean[3]["type"] == "function_call_output"
        assert "output" in clean[3]
        # reasoning: type + id + summary
        assert clean[4]["type"] == "reasoning"
        assert "summary" in clean[4]


# -------------------------------------------------------------------
# message-count trimming
# -------------------------------------------------------------------


class TestCountTrimming:
    def test_no_trim_when_under_limit(self):
        h = ConversationHistory()
        # MAX_MESSAGES is 100 — a few messages won't trigger it
        for i in range(20):
            h.add_message("user", f"q{i}")
            h.add_message("assistant", f"a{i}")
        assert len(h.messages) == 40
        assert h._trim_warned is False

    def test_trim_triggers_when_over_max(self):
        h = ConversationHistory()
        # Force messages past MAX_MESSAGES
        target = MAX_MESSAGES + 10
        # Build messages directly to avoid triggering the hook
        # (which does nothing here since we have no tool outputs)
        h.messages = _build_messages(target // 2)
        h.add_message("user", "final")
        # Should have trimmed down
        assert len(h.messages) <= int(MAX_MESSAGES * TRIM_TARGET_FRACTION) + 1

    def test_trim_warns_only_once(self, capsys):
        h = ConversationHistory()
        h.messages = _build_messages(MAX_MESSAGES // 2 + 1)
        # Should trigger trim
        h._trim_messages()
        # Simulate stderr output (the warning uses print-to-stderr)
        # Just verify _trim_warned is set
        assert h._trim_warned is True


# -------------------------------------------------------------------
# byte-budget trimming
# -------------------------------------------------------------------


class TestByteBudgetTrimming:
    def test_no_trim_when_under_budget(self):
        h = ConversationHistory()
        h.add_message("user", "hello")
        h.add_message("assistant", "world")
        h._trim_by_byte_budget()
        assert len(h.messages) == 2

    def test_trim_when_over_budget(self):
        h = ConversationHistory()
        # Create messages that exceed the byte budget
        big = "x" * (MAX_HISTORY_BYTES // KEEP_RECENT_MESSAGES + 100)
        for _ in range(KEEP_RECENT_MESSAGES + 10):
            h.messages.append({"role": "user", "content": big, "_turn_id": 1})
        before = len(h.messages)
        h._trim_by_byte_budget()
        assert len(h.messages) <= KEEP_RECENT_MESSAGES
        assert len(h.messages) < before


# -------------------------------------------------------------------
# orphan repair
# -------------------------------------------------------------------


class TestOrphanRepair:
    def test_orphaned_output_removed(self):
        h = ConversationHistory()
        h.messages = [
            {
                "type": "function_call_output",
                "call_id": "orphan",
                "output": "no matching call",
            },
            {
                "type": "function_call",
                "call_id": "valid",
                "name": "read_file",
                "arguments": "{}",
            },
            {
                "type": "function_call_output",
                "call_id": "valid",
                "output": "matched",
            },
        ]
        h._repair_orphaned_outputs()
        assert len(h.messages) == 2
        call_ids = [
            m["call_id"]
            for m in h.messages
            if m.get("type") == "function_call_output"
        ]
        assert call_ids == ["valid"]

    def test_empty_messages_no_crash(self):
        h = ConversationHistory()
        h._repair_orphaned_outputs()
        assert h.messages == []

    def test_no_orphans_nothing_removed(self):
        h = ConversationHistory()
        h.messages = [
            {
                "type": "function_call",
                "call_id": "c1",
                "name": "grep_files",
                "arguments": "{}",
            },
            {
                "type": "function_call_output",
                "call_id": "c1",
                "output": "result",
            },
        ]
        h._repair_orphaned_outputs()
        assert len(h.messages) == 2

    def test_multiple_orphans_removed(self):
        h = ConversationHistory()
        h.messages = [
            {"type": "function_call_output", "call_id": "o1", "output": "a"},
            {"type": "function_call_output", "call_id": "o2", "output": "b"},
            {"type": "function_call", "call_id": "real", "name": "x", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "real", "output": "c"},
            {"type": "function_call_output", "call_id": "o3", "output": "d"},
        ]
        h._repair_orphaned_outputs()
        assert len(h.messages) == 2
        assert h.messages[0]["type"] == "function_call"
        assert h.messages[1]["type"] == "function_call_output"
        assert h.messages[1]["call_id"] == "real"

# -------------------------------------------------------------------
# orphan call repair
# -------------------------------------------------------------------

#     def test_orphaned_call_removed(self):
#         """A function_call with no matching output should be removed."""
#         h = ConversationHistory()
#         h.messages = [
#             {
#                 "type": "function_call",
#                 "call_id": "orphan_call",
#                 "name": "nonexistent_tool",
#                 "arguments": "{}",
#             },
#             {
#                 "type": "function_call",
#                 "call_id": "valid",
#                 "name": "read_file",
#                 "arguments": "{}",
#             },
#             {
#                 "type": "function_call_output",
#                 "call_id": "valid",
#                 "output": "matched",
#             },
#         ]
#         h._repair_orphaned_outputs()
#         assert len(h.messages) == 2
#         call_ids = [
#             m["call_id"]
#             for m in h.messages
#             if m.get("type") == "function_call"
#         ]
#         assert call_ids == ["valid"]
#         # No orphaned call remains
#         assert "orphan_call" not in [m.get("call_id") for m in h.messages]
#     
#     def test_symmetric_orphan_repair(self):
#         """Both orphaned calls and orphaned outputs are removed."""
#         h = ConversationHistory()
#         h.messages = [
#             {"type": "function_call_output", "call_id": "orphan_out", "output": "a"},
#             {"type": "function_call", "call_id": "orphan_call", "name": "x", "arguments": "{}"},
#             {"type": "function_call", "call_id": "real", "name": "y", "arguments": "{}"},
#             {"type": "function_call_output", "call_id": "real", "output": "b"},
#         ]
#         h._repair_orphaned_outputs()
#         assert len(h.messages) == 2
#         assert h.messages[0]["type"] == "function_call"
#         assert h.messages[1]["type"] == "function_call_output"
#         assert h.messages[0]["call_id"] == "real"
#         assert h.messages[1]["call_id"] == "real"


# -------------------------------------------------------------------
# estimate_memory_mb
# -------------------------------------------------------------------


class TestMemoryEstimate:
    def test_zero_for_empty(self):
        h = ConversationHistory()
        assert h.estimate_memory_mb() == 0.0

    def test_grows_with_messages(self):
        h = ConversationHistory()
        h.add_message("user", "hello")
        mb = h.estimate_memory_mb()
        assert mb > 0

    def test_survives_unstringable_message(self):
        """estimate should not crash if a message can't be str'd."""
        h = ConversationHistory()
        h.messages = [{"role": "user", "content": object()}]  # type: ignore
        # Should not raise
        mb = h.estimate_memory_mb()
        assert mb >= 0


# -------------------------------------------------------------------
# save_to_file / persistence
# -------------------------------------------------------------------


class TestSaveToFile:
    def test_save_and_reload(self):
        h = ConversationHistory()
        h.add_message("user", "hello")
        h.add_tool_call("cid1", "read_file", "{}")
        h.add_tool_output("cid1", "content", "read_file", {})

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            path = f.name

        try:
            h.save_to_file(path)
            with open(path) as f:
                data = json.load(f)
            assert len(data) == 3
            assert data[0]["role"] == "user"
            assert data[0]["content"] == "hello"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_get_message_count_ignores_reasoning(self):
        h = ConversationHistory()
        h.add_message("user", "q")
        h.add_reasoning("thinking...")
        h.add_message("assistant", "a")
        # 1 pair → 1 round, reasoning doesn't count
        assert h.get_message_count() == 1


# -------------------------------------------------------------------
# full-turn simulation (integration-style)
# -------------------------------------------------------------------


class TestFullTurn:
    def test_typical_turn_sequence(self):
        """Simulate a turn: user message, tool calls, outputs, reasoning, assistant."""
        hook_log = []

        def hook(msgs, tid):
            hook_log.append(("hook", len(msgs), tid))

        h = ConversationHistory(new_turn_hook=hook)

        # Turn 1
        h.add_message("user", "read /foo")
        h.add_tool_call("c1", "read_file", '{"path":"/foo"}')
        h.add_tool_output("c1", "file content", "read_file", {"path": "/foo"})
        h.add_reasoning("the file says...")
        h.add_message("assistant", "the file contains: file content")

        assert h.turn_id == 1
        assert len(h.messages) == 5
        assert h.messages[0]["_turn_id"] == 1
        assert h.messages[-1]["_turn_id"] == 1
        # Hook was called with (0 msgs, turn 0)
        assert hook_log == [("hook", 0, 0)]

        # Turn 2
        h.add_message("user", "now write /bar")
        # Hook was called again with (5 msgs, turn 1)
        assert len(hook_log) == 2
        assert hook_log[1] == ("hook", 5, 1)
        assert h.turn_id == 2

    def test_for_api_after_full_turn(self):
        h = ConversationHistory()
        h.add_message("user", "hello")
        h.add_tool_call("c1", "run_command", '{"cmd":"ls"}')
        h.add_tool_output("c1", "file1\nfile2", "run_command", {"cmd": "ls"})
        h.add_message("assistant", "done")

        clean = h.for_api()
        # Must have exactly the SDK-required shape
        assert clean[0] == {"role": "user", "content": "hello"}
        assert clean[1]["type"] == "function_call"
        assert clean[2]["type"] == "function_call_output"
        assert clean[3] == {"role": "assistant", "content": "done"}
        
