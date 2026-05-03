import json
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from agents import ToolApprovalItem
from agents.tool import FunctionTool

from copane.tmux_agent import TmuxAgent


class TestToolApproval:
    """Tests for the SDK-level approval flow.

    The approval gate lives in the SDK runner, not in the tool body.
    We test the app-layer handling code directly here.
    """

    @pytest.fixture
    def agent(self):
        return TmuxAgent(name="test-agent")

    @pytest.fixture
    def approval_item(self):
        """Create a minimal ToolApprovalItem for write_file."""
        # Build a mock-like raw_item — ToolApprovalItem accepts a dict
        # as raw_item (see ToolApprovalRawItem type alias).
        raw_item = {
            "name": "write_file",
            "arguments": json.dumps({
                "path": "/tmp/test.txt",
                "content": "hello world",
            }),
        }
        return ToolApprovalItem(
            agent=MagicMock(),
            raw_item=raw_item,
            tool_name="write_file",
        )

    @pytest.fixture
    def state(self, agent):
        """Create a mock RunState that records approval/rejection calls."""
        state = MagicMock()
        return state

    # -- State-level approval/rejection tests --

    def test_approve(self, agent, approval_item, state):
        agent.handle_tool_approval(approval_item, "y", state)
        state.approve.assert_called_once_with(approval_item)

    def test_reject(self, agent, approval_item, state):
        agent.handle_tool_approval(approval_item, "n", state)
        state.reject.assert_called_once_with(approval_item)

    def test_always_approve(self, agent, approval_item, state):
        agent.handle_tool_approval(approval_item, "a", state)
        state.approve.assert_called_once_with(approval_item, always_approve=True)

    def test_always_reject(self, agent, approval_item, state):
        agent.handle_tool_approval(approval_item, "r", state)
        state.reject.assert_called_once_with(approval_item, always_reject=True)

    def test_quit_raises_keyboard_interrupt(self, agent, approval_item, state):
        with pytest.raises(KeyboardInterrupt, match="Tool approval process interrupted"):
            agent.handle_tool_approval(approval_item, "q", state)

    def test_invalid_decision(self, agent, approval_item, state):
        with pytest.raises(ValueError, match="Invalid decision"):
            agent.handle_tool_approval(approval_item, "x", state)

    # -- Integration-level: preview generation from ToolApprovalItem args --

    def test_format_tool_preview(self, approval_item):
        from copane.preview import format_tool_preview
        preview = format_tool_preview(approval_item)
        assert "write_file" in preview
        assert "/tmp/test.txt" in preview
        assert "hello world" in preview

    # -- Template for full integration test (requires mocked runner) --

    async def test_approval_interruption_flow(self, monkeypatch, agent, approval_item, state):
        """Test that the yield/resume loop works end-to-end.

        This mocks Runner.run_streamed to return a result with an interruption,
        then verifies the generator yields a 'tool_approval' event.
        """
        from agents import Runner
        from agents.result import RunResultStreaming

        # Mock the first run: return a result with one interruption
        mock_result = MagicMock(spec=RunResultStreaming)
        mock_result.interruptions = [approval_item]
        mock_result.to_state.return_value = state

        # Mock the second run (after approval): return a result with no interruptions
        mock_result2 = MagicMock(spec=RunResultStreaming)
        mock_result2.interruptions = []

        # Make stream_events yield nothing for simplicity
        async def empty_stream():
            return
            yield  # pragma: no cover

        mock_result.stream_events = empty_stream
        mock_result2.stream_events = empty_stream

        monkeypatch.setattr(Runner, "run_streamed", lambda *a, **kw: mock_result if kw.get('state') is None else mock_result2)

        # Mock handle_tool_approval to approve immediately
        agent.handle_tool_approval = MagicMock()

        events = []
        async for event in agent.stream_response("write a file"):
            events.append(event)

        # Should have yielded a tool_approval event
        approval_events = [e for e in events if e[0] == 'tool_approval']
        assert len(approval_events) == 1
        item, st = approval_events[0][1]
        assert item.tool_name == "write_file"

