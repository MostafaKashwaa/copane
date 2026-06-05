"""Tests for TmuxAgent — conversation flow, event handling, streaming, and memory.

Pure unit tests with mocked SDK objects. No live LLM, no network calls.
Covers all sections from ``guides/TMUX_AGENT_TEST_PLAN.md`` except the
3 additional ``handle_tool_approval`` edge cases (those live in
``test_tool_approval.py``).
"""

import gc
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents import (
    Agent,
    RawResponsesStreamEvent,
    RunItemStreamEvent,
    Runner,
    ToolApprovalItem,
)
from openai.types.responses import (
    ResponseReasoningTextDeltaEvent,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseTextDeltaEvent,
)

from copane import tools as tools_pkg
from copane.conversation_history import ConversationHistory
from copane.model_config import ModelConfig
from copane.model_provider import ModelProvider
from copane.tmux_agent import TmuxAgent, get_agent, _agent as _global_agent


# -------------------------------------------------------------------
# helpers
# -------------------------------------------------------------------


def _make_raw_event(delta_event_cls, delta_text: str = "hello"):
    """Build a ``RawResponsesStreamEvent`` whose ``.data`` is *delta_event_cls*."""
    # All OpenAI delta events require these fields - fill with dummy data
    common = {
        "content_index": 0,
        "item_id": "item-123",
        "output_index": 0,
        "sequence_number": 1,
    }
    extra = {}
    if issubclass(delta_event_cls, ResponseReasoningTextDeltaEvent):
        extra["type"] = "response.reasoning_text.delta"
        extra["reasoning_index"] = 0
    elif issubclass(delta_event_cls, ResponseReasoningSummaryTextDeltaEvent):
        extra["type"] = "response.reasoning_summary_text.delta"
        extra["summary_index"] = 0  # specific to summary deltas    
    elif issubclass(delta_event_cls, ResponseTextDeltaEvent):
        extra["logprobs"] = []
        extra["type"] = "response.output_text.delta"
    data = delta_event_cls(delta=delta_text, **common, **extra)
    event = MagicMock(spec=RawResponsesStreamEvent)
    event.data = data
    return event


def _make_run_item_event_tool_called(call_id: str, name: str, arguments):
    """Build a ``RunItemStreamEvent`` for the ``tool_called`` phase.

    *arguments* can be a JSON string, a dict, or ``None``.
    """
    raw_item = MagicMock()
    raw_item.call_id = call_id
    raw_item.name = name
    raw_item.arguments = arguments

    item = MagicMock()
    item.raw_item = raw_item

    event = MagicMock(spec=RunItemStreamEvent)
    event.name = "tool_called"
    event.item = item
    return event


def _make_run_item_event_tool_output(
    call_id: str, output, raw_item_as_dict: bool = True
):
    """Build a ``RunItemStreamEvent`` for the ``tool_output`` phase.

    When *raw_item_as_dict* is True, ``raw_item`` is a dict with
    ``"call_id"`` (the real SDK shape).  When False, it is a Pydantic
    model stub (defensive path).
    """
    item = MagicMock()
    item.output = output
    if raw_item_as_dict:
        item.raw_item = {"call_id": call_id}
    else:
        raw = MagicMock()
        raw.call_id = call_id  # attribute, not dict key
        item.raw_item = raw

    event = MagicMock(spec=RunItemStreamEvent)
    event.name = "tool_output"
    event.item = item
    return event


def _make_run_item_event_unknown():
    """Build a ``RunItemStreamEvent`` with an unrecognised name."""
    event = MagicMock(spec=RunItemStreamEvent)
    event.name = "some_future_event"
    return event


# ── helper: create a TmuxAgent with fully mocked internals ────────────


def _build_agent(**overrides):
    """Create a TmuxAgent with every dependency mocked.

    All mocks are accessible as attributes on the returned agent so
    tests can assert on them directly.
    """
    agent = TmuxAgent.__new__(TmuxAgent)
    agent.name = overrides.get("name", "test-agent")
    agent._session_id = overrides.get("session_id", "test-2025-01-01_00-00-00-abc123")
    agent._first_user_message = overrides.get("_first_user_message", "")
    agent._title = overrides.get("_title", None)
    agent._title_generated = overrides.get("_title_generated", False)
    agent._save_session = MagicMock()
    agent.save_current_session = MagicMock()
    agent._generate_title = AsyncMock()

    # conversation history (with mocked methods)
    mock_history = MagicMock(spec=ConversationHistory)
    mock_history.messages = []
    mock_history._current_turn_start_index = 0
    mock_history.estimate_memory_mb.return_value = 10.0  # well under 50 MB
    mock_history.total_input_tokens = overrides.get("total_input_tokens", 0)
    mock_history.total_output_tokens = overrides.get("total_output_tokens", 0)
    agent.history = mock_history

    # model config
    agent.model_config = MagicMock(spec=ModelConfig)

    # model provider
    mock_provider = MagicMock(spec=ModelProvider)
    mock_provider.get_model_info.return_value = {
        "key": "deepseek-chat",
        "name": "deepseek-chat",
        "description": "test",
        "type": "api",
        "base_url": "",
        "env_key": "",
        "status": "configured",
    }
    mock_provider.list_available_models.return_value = {
        "deepseek-chat": {
            "name": "deepseek-chat",
            "description": "test",
            "type": "api",
            "status": "configured",
            "is_selected": True,
        }
    }
    mock_provider.create_agent.return_value = MagicMock(spec=Agent)
    agent.model_provider = mock_provider

    # tools
    agent.tools = [
        MagicMock() for _ in range(7)
    ]
    for i, name in enumerate(
        ["edit_file", "read_file", "run_command", "grep_files",
            "list_files", "write_file", "get_current_dir"]
    ):
        agent.tools[i].name = name

    # agent (the SDK Agent — None by default)
    agent.agent = overrides.get("agent", None)

    return agent


# -------------------------------------------------------------------
# 1. __init__
# -------------------------------------------------------------------


class TestInit:
    def test_creates_history(self):
        a = TmuxAgent(name="test")
        assert isinstance(a.history, ConversationHistory)

    def test_sets_name(self):
        a = TmuxAgent(name="my-agent")
        assert a.name == "my-agent"

    def test_has_all_seven_tools(self):
        a = TmuxAgent(name="test")
        assert len(a.tools) == 7
        names = {t.name for t in a.tools}
        assert names == {
            "edit_file",
            "read_file",
            "run_command",
            "grep_files",
            "list_files",
            "write_file",
            "get_current_dir",
        }

    def test_agent_is_none_initially(self):
        a = TmuxAgent(name="test")
        assert a.agent is None

    def test_creates_model_provider_with_model_config(self):
        a = TmuxAgent(name="test")
        assert isinstance(a.model_provider, ModelProvider)
        assert a.model_provider.model_config is a.model_config

    def test_no_new_turn_hook(self):
        """_new_turn_hook is None — summarization runs at end of turn."""
        a = TmuxAgent(name="test")
        assert a.history._new_turn_hook is None


# -------------------------------------------------------------------
# 2. Model management delegators
# -------------------------------------------------------------------


class TestModelDelegators:
    def test_get_model_info_delegates(self):
        a = _build_agent()
        result = a.get_model_info()
        a.model_provider.get_model_info.assert_called_once()
        assert result is a.model_provider.get_model_info.return_value

    def test_list_available_models_delegates(self):
        a = _build_agent()
        result = a.list_available_models()
        a.model_provider.list_available_models.assert_called_once()
        assert result is a.model_provider.list_available_models.return_value

    def test_switch_model_delegates_and_invalidates(self):
        a = _build_agent()
        a.agent = MagicMock()  # set an agent so we can verify invalidation
        a.switch_model("gpt-4o")
        a.model_provider.switch_model.assert_called_once_with("gpt-4o")
        assert a.agent is None

    def test_switch_model_raises_propagates(self):
        a = _build_agent()
        a.model_provider.switch_model.side_effect = ValueError("not found")
        with pytest.raises(ValueError, match="not found"):
            a.switch_model("bad")

    def test_setup_delegates_and_stores(self):
        a = _build_agent()
        a.setup()
        a.model_provider.create_agent.assert_called_once_with(
            a.tools, a.name
        )
        assert a.agent is a.model_provider.create_agent.return_value


# -------------------------------------------------------------------
# 3. handle_tool_approval — additional edge cases
#    (existing base tests live in test_tool_approval.py)
# -------------------------------------------------------------------


class TestToolApprovalEdgeCases:
    """3 extra edge-case tests not covered by test_tool_approval.py."""

    @pytest.fixture
    def agent(self):
        return _build_agent()

    @pytest.fixture
    def approval_item(self):
        raw_item = {
            "name": "write_file",
            "arguments": json.dumps({"path": "/x", "content": "hi"}),
        }
        return ToolApprovalItem(
            agent=MagicMock(),
            raw_item=raw_item,
            tool_name="write_file",
        )

    @pytest.fixture
    def state(self):
        return MagicMock()

    def test_reject_message_contains_guidance(self, agent, approval_item, state):
        agent.handle_tool_approval(approval_item, "n", state)
        _, kwargs = state.reject.call_args
        assert (
            "If you can't proceed without this tool call"
            in kwargs["rejection_message"]
        )

    def test_retry_message_mentions_different_approach(
        self, agent, approval_item, state
    ):
        agent.handle_tool_approval(approval_item, "r", state)
        _, kwargs = state.reject.call_args
        assert "Try a different approach" in kwargs["rejection_message"]

    @pytest.mark.parametrize("decision", ["y", "n", "a", "r", "q"])
    def test_all_decisions_handled_without_crash(
        self, agent, approval_item, state, decision
    ):
        """Every valid decision string is handled (no unhandled exception)."""
        try:
            agent.handle_tool_approval(approval_item, decision, state)
        except RuntimeError:
            # "q" raises RuntimeError — that's the expected behaviour
            pass


# -------------------------------------------------------------------
# 4. _StreamingContext
# -------------------------------------------------------------------


class TestStreamingContext:
    def test_default_values(self):
        ctx = TmuxAgent._StreamingContext()
        assert ctx.thinking_response == ""
        assert ctx.text_response == ""
        assert ctx.pending_tool_calls == {}

    def test_pending_tool_calls_is_mutable(self):
        ctx = TmuxAgent._StreamingContext()
        ctx.pending_tool_calls["c1"] = ("read_file", {"path": "/x"})
        assert "c1" in ctx.pending_tool_calls
        del ctx.pending_tool_calls["c1"]
        assert ctx.pending_tool_calls == {}

    def test_independent_instances(self):
        ctx1 = TmuxAgent._StreamingContext()
        ctx2 = TmuxAgent._StreamingContext()
        ctx1.pending_tool_calls["x"] = ("t", {})
        assert ctx2.pending_tool_calls == {}


# -------------------------------------------------------------------
# 5. _handle_raw_event
# -------------------------------------------------------------------


class TestHandleRawEvent:
    @pytest.fixture
    def agent(self):
        return _build_agent()

    def test_reasoning_text_delta_yields_thinking(self, agent):
        ctx = TmuxAgent._StreamingContext()
        event = _make_raw_event(ResponseReasoningTextDeltaEvent, "hmm")
        result = agent._handle_raw_event(event, ctx)
        assert result == ("thinking", "hmm")
        assert ctx.thinking_response == "hmm"

    def test_reasoning_summary_delta_yields_thinking(self, agent):
        ctx = TmuxAgent._StreamingContext()
        event = _make_raw_event(
            ResponseReasoningSummaryTextDeltaEvent, "summary")
        result = agent._handle_raw_event(event, ctx)
        assert result == ("thinking", "summary")
        assert ctx.thinking_response == "summary"

    def test_text_delta_yields_text(self, agent):
        ctx = TmuxAgent._StreamingContext()
        event = _make_raw_event(ResponseTextDeltaEvent, "code")
        result = agent._handle_raw_event(event, ctx)
        assert result == ("text", "code")
        assert ctx.text_response == "code"

    def test_empty_delta_still_yields(self, agent):
        ctx = TmuxAgent._StreamingContext()
        event = _make_raw_event(ResponseTextDeltaEvent, "")
        result = agent._handle_raw_event(event, ctx)
        assert result == ("text", "")
        assert ctx.text_response == ""

    def test_unknown_event_returns_none(self, agent):
        ctx = TmuxAgent._StreamingContext()
        event = MagicMock(spec=RawResponsesStreamEvent)
        event.data = MagicMock()  # not a delta event type
        result = agent._handle_raw_event(event, ctx)
        assert result is None

    def test_accumulates_across_multiple_calls(self, agent):
        ctx = TmuxAgent._StreamingContext()
        agent._handle_raw_event(
            _make_raw_event(ResponseReasoningTextDeltaEvent, "one"), ctx
        )
        agent._handle_raw_event(
            _make_raw_event(ResponseReasoningTextDeltaEvent, " two"), ctx
        )
        assert ctx.thinking_response == "one two"


# -------------------------------------------------------------------
# 6. _handle_run_item_event — tool_called
# -------------------------------------------------------------------


class TestHandleRunItemToolCalled:
    @pytest.fixture
    def agent(self):
        return _build_agent()

    def test_normal_tool_call_adds_to_history_and_pending(self, agent):
        ctx = TmuxAgent._StreamingContext()
        event = _make_run_item_event_tool_called(
            "call-1", "read_file", '{"path":"/x"}'
        )
        result = agent._handle_run_item_event(event, ctx)
        assert result == ("tool_call", ("read_file", "call-1"))
        agent.history.add_tool_call.assert_called_once_with(
            "call-1", "read_file", '{"path":"/x"}'
        )
        assert ctx.pending_tool_calls["call-1"] == (
            "read_file",
            '{"path":"/x"}',
        )

    def test_hallucinated_tool_adds_synthetic_error(self, agent):
        ctx = TmuxAgent._StreamingContext()
        event = _make_run_item_event_tool_called(
            "call-99", "super_hallucinated_tool", '{"x":1}'
        )
        result = agent._handle_run_item_event(event, ctx)
        assert result == ("tool_call", ("super_hallucinated_tool", "call-99"))
        # Should have added a synthetic error output
        agent.history.add_tool_output.assert_called_once()
        call_args = agent.history.add_tool_output.call_args
        assert call_args[0][0] == "call-99"  # call_id
        assert "attempted to call unknown tool" in call_args[0][1]
        assert "Available tools:" in call_args[0][1]

    def test_hallucinated_string_args_parse_ok(self, agent):
        ctx = TmuxAgent._StreamingContext()
        event = _make_run_item_event_tool_called(
            "call-99", "bad_tool", '{"path":"/x"}'
        )
        agent._handle_run_item_event(event, ctx)
        # The synthetic error output should have parsed tool_args
        call_args = agent.history.add_tool_output.call_args
        assert call_args[0][3] == {"path": "/x"}  # parsed

    def test_hallucinated_string_args_parse_fails(self, agent):
        ctx = TmuxAgent._StreamingContext()
        event = _make_run_item_event_tool_called(
            "call-99", "bad_tool", "not json at all"
        )
        agent._handle_run_item_event(event, ctx)
        call_args = agent.history.add_tool_output.call_args
        assert call_args[0][3] == {"raw": "not json at all"}

    def test_hallucinated_dict_args_no_parse(self, agent):
        ctx = TmuxAgent._StreamingContext()
        event = _make_run_item_event_tool_called(
            "call-99", "bad_tool", {"path": "/x"}
        )
        agent._handle_run_item_event(event, ctx)
        call_args = agent.history.add_tool_output.call_args
        assert call_args[0][3] == {"path": "/x"}

    def test_hallucinated_none_args(self, agent):
        ctx = TmuxAgent._StreamingContext()
        event = _make_run_item_event_tool_called("call-99", "bad_tool", None)
        agent._handle_run_item_event(event, ctx)
        call_args = agent.history.add_tool_output.call_args
        assert call_args[0][3] == {}

    def test_hallucinated_error_message_mentions_available_tools(self, agent):
        ctx = TmuxAgent._StreamingContext()
        event = _make_run_item_event_tool_called(
            "call-99", "bad_tool", "{}"
        )
        agent._handle_run_item_event(event, ctx)
        error_msg = agent.history.add_tool_output.call_args[0][1]
        assert "Available tools:" in error_msg
        assert "read_file" in error_msg
        assert "run_command" in error_msg


# -------------------------------------------------------------------
# 7. _handle_run_item_event — tool_output
# -------------------------------------------------------------------


class TestHandleRunItemToolOutput:
    @pytest.fixture
    def agent(self):
        return _build_agent()

    def test_normal_output_matched_to_pending_call(self, agent):
        ctx = TmuxAgent._StreamingContext()
        ctx.pending_tool_calls["call-1"] = (
            "read_file",
            '{"path":"/x"}',
        )
        event = _make_run_item_event_tool_output("call-1", "file content")
        result = agent._handle_run_item_event(event, ctx)
        assert result == ("tool_response", ("file content", "call-1"))
        agent.history.add_tool_output.assert_called_once_with(
            "call-1",
            "file content",
            "read_file",
            {"path": "/x"},
        )

    def test_call_id_not_in_pending_defaults_to_none(self, agent):
        ctx = TmuxAgent._StreamingContext()
        event = _make_run_item_event_tool_output("missing-call", "out")
        result = agent._handle_run_item_event(event, ctx)
        # name and args default to None/unknown
        agent.history.add_tool_output.assert_called_once_with(
            "missing-call",
            "out",
            "unknown",
            {},
        )

    def test_call_id_none_skips_lookup(self, agent):
        """When raw_item is NOT a dict, tool_call_id is None → skips lookup."""
        ctx = TmuxAgent._StreamingContext()
        event = _make_run_item_event_tool_output(
            "call-1", "out", raw_item_as_dict=False
        )
        agent._handle_run_item_event(event, ctx)
        # tool_call_id is None → tool_name and tool_args are None
        agent.history.add_tool_output.assert_called_once_with(
            "", "out", "unknown", {}
        )

    def test_raw_item_is_dict_extracts_call_id(self, agent):
        ctx = TmuxAgent._StreamingContext()
        event = _make_run_item_event_tool_output(
            "xyz-123", "output", raw_item_as_dict=True
        )
        # The helper already builds this shape — just verify it works
        agent._handle_run_item_event(event, ctx)
        # Should have called add_tool_output with call_id "xyz-123"
        assert agent.history.add_tool_output.call_args[0][0] == "xyz-123"

    def test_output_not_string_converted(self, agent):
        ctx = TmuxAgent._StreamingContext()
        event = _make_run_item_event_tool_output("call-1", 42)
        agent._handle_run_item_event(event, ctx)
        call_args = agent.history.add_tool_output.call_args
        assert call_args[0][1] == "42"  # converted to str

    def test_tool_args_json_string_parsed(self, agent):
        ctx = TmuxAgent._StreamingContext()
        ctx.pending_tool_calls["call-1"] = (
            "run_command",
            '{"cmd":"ls -la"}',
        )
        event = _make_run_item_event_tool_output("call-1", "output")
        agent._handle_run_item_event(event, ctx)
        call_args = agent.history.add_tool_output.call_args
        assert call_args[0][3] == {"cmd": "ls -la"}

    def test_tool_args_dict_passed_through(self, agent):
        ctx = TmuxAgent._StreamingContext()
        ctx.pending_tool_calls["call-1"] = (
            "run_command",
            {"cmd": "ls -la"},
        )
        event = _make_run_item_event_tool_output("call-1", "output")
        agent._handle_run_item_event(event, ctx)
        call_args = agent.history.add_tool_output.call_args
        assert call_args[0][3] == {"cmd": "ls -la"}

    def test_returns_tool_response_tuple(self, agent):
        ctx = TmuxAgent._StreamingContext()
        event = _make_run_item_event_tool_output("call-1", "done")
        result = agent._handle_run_item_event(event, ctx)
        assert result[0] == "tool_response"
        # assert result[1] == "done"
        assert result == ("tool_response", ("done", "call-1"))


# -------------------------------------------------------------------
# 8. _handle_run_item_event — unknown event name
# -------------------------------------------------------------------


class TestHandleRunItemUnknown:
    @pytest.fixture
    def agent(self):
        return _build_agent()

    def test_unknown_event_name_returns_none(self, agent):
        ctx = TmuxAgent._StreamingContext()
        event = _make_run_item_event_unknown()
        result = agent._handle_run_item_event(event, ctx)
        assert result is None


# -------------------------------------------------------------------
# 9. _process_runner_events
# -------------------------------------------------------------------


class TestProcessRunnerEvents:
    @pytest.fixture
    def agent(self):
        return _build_agent()

    @pytest.mark.asyncio
    async def test_raw_event_delegated_and_yielded(self, agent):
        ctx = TmuxAgent._StreamingContext()
        mock_response = MagicMock()
        event = _make_raw_event(ResponseTextDeltaEvent, "hi")

        async def _stream():
            yield event

        mock_response.stream_events = _stream

        results = []
        async for r in agent._process_runner_events(mock_response, ctx):
            results.append(r)
        assert results == [("text", "hi")]

    @pytest.mark.asyncio
    async def test_run_item_event_delegated_and_yielded(self, agent):
        ctx = TmuxAgent._StreamingContext()
        mock_response = MagicMock()
        event = _make_run_item_event_tool_called(
            "call-1", "read_file", '{"path":"/x"}'
        )

        async def _stream():
            yield event

        mock_response.stream_events = _stream

        results = []
        async for r in agent._process_runner_events(mock_response, ctx):
            results.append(r)
        assert results[0] == ("tool_call", ("read_file", "call-1"))

    @pytest.mark.asyncio
    async def test_handle_returns_none_not_yielded(self, agent):
        ctx = TmuxAgent._StreamingContext()
        mock_response = MagicMock()
        # A RawResponsesStreamEvent whose data is not a delta type
        unknown_event = MagicMock(spec=RawResponsesStreamEvent)
        unknown_event.data = MagicMock()

        async def _stream():
            yield unknown_event

        mock_response.stream_events = _stream

        results = []
        async for r in agent._process_runner_events(mock_response, ctx):
            results.append(r)
        assert results == []


# -------------------------------------------------------------------
# 10. _store_reasoning
# -------------------------------------------------------------------


class TestStoreReasoning:
    @pytest.fixture
    def agent(self):
        return _build_agent()

    def test_non_empty_reasoning_stored(self, agent):
        agent._store_reasoning("thought process")
        agent.history.add_reasoning.assert_called_once_with("thought process")

    def test_empty_reasoning_still_delegated(self, agent):
        agent._store_reasoning("")
        agent.history.add_reasoning.assert_called_once_with("")


# -------------------------------------------------------------------
# 11. _print_memory_warning
# -------------------------------------------------------------------


class TestPrintMemoryWarning:
    @pytest.fixture
    def agent(self):
        return _build_agent()

    def test_below_50mb_no_warning(self, agent, capsys):
        agent.history.estimate_memory_mb.return_value = 30.0
        agent._print_memory_warning()
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_above_50mb_prints_warning(self, agent, capsys):
        agent.history.estimate_memory_mb.return_value = 75.0
        agent.history.messages = [{}] * 42  # fake message count
        agent._print_memory_warning()
        captured = capsys.readouterr()
        assert "/clear" in captured.err
        assert "42 messages" in captured.err
        assert "75.0 MB" in captured.err

    def test_exactly_50mb_no_warning(self, agent, capsys):
        agent.history.estimate_memory_mb.return_value = 50.0
        agent._print_memory_warning()
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_warning_includes_message_count_and_mb(self, agent, capsys):
        agent.history.estimate_memory_mb.return_value = 120.0
        agent.history.messages = [{}] * 100
        agent._print_memory_warning()
        captured = capsys.readouterr()
        assert "100 messages" in captured.err
        assert "120.0 MB" in captured.err


# -------------------------------------------------------------------
# 12. _recreate_runner
# -------------------------------------------------------------------


class TestRecreateRunner:
    @pytest.fixture
    def agent(self):
        a = _build_agent()
        a.agent = MagicMock(spec=Agent)
        return a

    def test_calls_gc_collect(self, agent):
        with patch.object(gc, "collect") as mock_collect:
            with patch.object(Runner, "run_streamed") as mock_run_streamed:
                mock_run_streamed.return_value = MagicMock()
                response = MagicMock()
                state = MagicMock()
                agent._recreate_runner(response, state)
                mock_collect.assert_called_once()

    def test_returns_new_runner_result(self, agent):
        with patch.object(gc, "collect"):
            with patch.object(Runner, "run_streamed") as mock_run_streamed:
                expected = MagicMock()
                mock_run_streamed.return_value = expected
                response = MagicMock()
                state = MagicMock()
                result = agent._recreate_runner(response, state)
                assert result is expected

    def test_passes_correct_args_to_runner(self, agent):
        with patch.object(gc, "collect"):
            with patch.object(Runner, "run_streamed") as mock_run_streamed:
                response = MagicMock()
                state = MagicMock()
                agent._recreate_runner(response, state)
                from copane.tmux_agent import MAX_TOOL_TURNS
                mock_run_streamed.assert_called_once_with(
                    agent.agent,
                    state,
                    max_turns=MAX_TOOL_TURNS,
                )


# -------------------------------------------------------------------
# 13. stream_response — structural
# -------------------------------------------------------------------


class TestStreamResponse:
    @pytest.fixture
    def agent(self):
        a = _build_agent()
        a.agent = MagicMock(spec=Agent)
        a.setup = MagicMock()
        a._store_reasoning = MagicMock()
        a._print_memory_warning = MagicMock()
        return a

    def _mock_streamed_result(self, events=None, interruptions=None):
        """Build a mock Runner result with controllable stream_events and interruptions."""
        result = MagicMock()
        result.interruptions = interruptions or []

        async def _stream():
            for e in (events or []):
                yield e

        result.stream_events = _stream
        result.to_state = MagicMock(return_value=MagicMock())
        return result

    # ── setup trigger ──

    @pytest.mark.asyncio
    async def test_calls_setup_when_agent_is_none(self, agent):
        agent.agent = None
        result = self._mock_streamed_result()

        with patch.object(Runner, "run_streamed", return_value=result):
            events = []
            async for e in agent.stream_response("hi"):
                events.append(e)

        agent.setup.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_setup_when_agent_exists(self, agent):
        result = self._mock_streamed_result()

        with patch.object(Runner, "run_streamed", return_value=result):
            events = []
            async for e in agent.stream_response("hi"):
                events.append(e)

        agent.setup.assert_not_called()

    # ── history interaction ──

    @pytest.mark.asyncio
    async def test_adds_user_message_to_history(self, agent):
        result = self._mock_streamed_result()

        with patch.object(Runner, "run_streamed", return_value=result):
            events = []
            async for e in agent.stream_response("hello world"):
                events.append(e)

        agent.history.add_message.assert_any_call("user", "hello world")

    # ── no-interruption path ──

    @pytest.mark.asyncio
    async def test_no_interruptions_yields_events_and_stores(self, agent):
        event = _make_raw_event(ResponseTextDeltaEvent, "hello")
        result = self._mock_streamed_result(events=[event])

        with patch.object(Runner, "run_streamed", return_value=result):
            events = []
            async for e in agent.stream_response("hi"):
                events.append(e)

        assert events == [("text", "hello")]
        agent._store_reasoning.assert_called_once()
        agent.history.add_message.assert_any_call("assistant", "hello")
        agent._print_memory_warning.assert_called_once()

    # ── one interruption ──

    @pytest.mark.asyncio
    async def test_one_interruption_resumes_after_approval(self, agent):
        approval_item = MagicMock(spec=ToolApprovalItem)
        approval_item.tool_name = "write_file"

        first_result = self._mock_streamed_result(
            interruptions=[approval_item])
        second_result = self._mock_streamed_result(events=[])

        run_count = [0]

        def _run_streamed(*args, **kwargs):
            run_count[0] += 1
            if run_count[0] == 1:
                return first_result
            else:
                return second_result

        with patch.object(Runner, "run_streamed", side_effect=_run_streamed):
            with patch.object(gc, "collect"):
                events = []
                async for e in agent.stream_response("hi"):
                    events.append(e)

        # Should have yielded a tool_approval event
        approval_events = [e for e in events if e[0] == "tool_approval"]
        assert len(approval_events) == 1
        assert approval_events[0][1][0] is approval_item

    # ── multiple interruptions ──

    @pytest.mark.asyncio
    async def test_multiple_interruptions_loop_correctly(self, agent):
        item1 = MagicMock(spec=ToolApprovalItem)
        item2 = MagicMock(spec=ToolApprovalItem)
        item3 = MagicMock(spec=ToolApprovalItem)

        results = [
            self._mock_streamed_result(interruptions=[item1]),
            self._mock_streamed_result(interruptions=[item2]),
            self._mock_streamed_result(interruptions=[item3]),
            # final round — no interruptions
            self._mock_streamed_result(events=[]),
        ]
        call_idx = [0]

        def _run_streamed(*args, **kwargs):
            idx = call_idx[0]
            call_idx[0] += 1
            return results[idx]

        with patch.object(Runner, "run_streamed", side_effect=_run_streamed):
            with patch.object(gc, "collect"):
                events = []
                async for e in agent.stream_response("hi"):
                    events.append(e)

        approval_events = [e for e in events if e[0] == "tool_approval"]
        assert len(approval_events) == 3


# -------------------------------------------------------------------
# 14. _summarize_current_turn
# -------------------------------------------------------------------


class TestSummarizeCurrentTurn:
    """Assert summarization fires at the end of every complete response."""

    @pytest.fixture
    def agent(self):
        a = _build_agent()
        a.agent = MagicMock(spec=Agent)
        a.setup = MagicMock()
        a._store_reasoning = MagicMock()
        a._print_memory_warning = MagicMock()
        return a

    @pytest.mark.asyncio
    async def test_summarize_called_before_save_session(self, agent):
        """``_summarize_current_turn`` must be called before ``_save_session``."""
        call_order = []

        def _fake_summarize():
            call_order.append("summarize")

        def _fake_save():
            call_order.append("save")

        agent._summarize_current_turn = _fake_summarize
        agent._save_session = _fake_save

        result = MagicMock()
        result.interruptions = []

        async def _empty_stream():
            return
            yield  # pragma: no cover — makes this an async generator

        result.stream_events = _empty_stream
        result.to_state = MagicMock(return_value=MagicMock())

        with patch.object(Runner, "run_streamed", return_value=result):
            async for _ in agent.stream_response("hi"):
                pass

        assert call_order == ["summarize", "save"]


# -------------------------------------------------------------------
# 15. get_agent singleton
# -------------------------------------------------------------------


class TestGetAgent:
    def teardown_method(self):
        # Reset the global after each test so tests don't leak
        import copane.tmux_agent as mod
        mod._agent = None

    def test_first_call_creates_instance(self):
        a = get_agent()
        assert isinstance(a, TmuxAgent)

    def test_second_call_returns_same_instance(self):
        a1 = get_agent()
        a2 = get_agent()
        assert a1 is a2

    def test_reset_global_creates_new_instance(self):
        a1 = get_agent()
        import copane.tmux_agent as mod
        mod._agent = None
        a2 = get_agent()
        assert a1 is not a2


# -------------------------------------------------------------------
# 16. Bug regression guards
# -------------------------------------------------------------------


class TestBugRegressionGuards:
    """Tests explicitly covering bugs documented in TMUX_AGENT_BUG_ANALYSIS.md."""

    @pytest.fixture
    def agent(self):
        return _build_agent()

    def test_hallucinated_tool_does_not_leave_orphan(self, agent):
        """Hallucinated tool → synthetic error output has same call_id → no orphan."""
        ctx = TmuxAgent._StreamingContext()

        # Simulate a hallucinated tool call
        event_called = _make_run_item_event_tool_called(
            "call-orphan-1", "nonexistent_tool", "{}"
        )
        agent._handle_run_item_event(event_called, ctx)

        # The synthetic error output should have been added
        agent.history.add_tool_output.assert_called_once()
        assert agent.history.add_tool_output.call_args[0][0] == "call-orphan-1"

        # Now simulate the tool_output event arriving — it should find the
        # pending entry
        ctx.pending_tool_calls["call-orphan-1"] = (
            "nonexistent_tool",
            "{}",
        )
        event_output = _make_run_item_event_tool_output(
            "call-orphan-1", "some output"
        )
        agent._handle_run_item_event(event_output, ctx)

        # Should have TWO add_tool_output calls (one synthetic error, one real output)
        # and the second call should also reference the same call_id
        assert agent.history.add_tool_output.call_count == 2
        assert agent.history.add_tool_output.call_args_list[1][0][0] == "call-orphan-1"

    def test_both_paths_use_same_json_parsing(self, agent):
        """Both hallucinated-tool and tool_output paths use the same guard pattern."""
        ctx = TmuxAgent._StreamingContext()

        # Path 1: hallucinated tool with string args
        event_called = _make_run_item_event_tool_called(
            "c1", "bad_tool", '{"key":"value"}'
        )
        agent._handle_run_item_event(event_called, ctx)
        args1 = agent.history.add_tool_output.call_args[0][3]

        # Path 2: normal tool_output with string args
        ctx.pending_tool_calls["c2"] = ("run_command", '{"cmd":"ls"}')
        event_output = _make_run_item_event_tool_output("c2", "out")
        agent._handle_run_item_event(event_output, ctx)
        args2 = agent.history.add_tool_output.call_args_list[1][0][3]

        # Both should be parsed dicts, not raw JSON strings
        assert args1 == {"key": "value"}
        assert args2 == {"cmd": "ls"}

    def test_print_memory_warning_not_called_below_threshold(self, agent, capsys):
        """Normal conversation should NOT trigger the 50 MB warning."""
        agent.history.estimate_memory_mb.return_value = 10.0
        agent._print_memory_warning()
        captured = capsys.readouterr()
        assert captured.err == ""


# -------------------------------------------------------------------
# 17. Delegator completeness
# -------------------------------------------------------------------


class TestDelegators:
    @pytest.fixture
    def agent(self):
        return _build_agent()

    def test_add_message_delegates(self, agent):
        agent.add_message("user", "hi")
        agent.history.add_message.assert_called_once_with("user", "hi")

    def test_clear_messages_delegates(self, agent):
        agent.clear_messages()
        agent.history.clear.assert_called_once()

    def test_get_message_count_delegates(self, agent):
        agent.history.get_message_count.return_value = 5
        assert agent.get_message_count() == 5
        agent.history.get_message_count.assert_called_once()

    def test_save_conversation_delegates(self, agent):
        agent.save_conversation("/tmp/x.json")
        agent.history.save_to_file.assert_called_once_with("/tmp/x.json")
