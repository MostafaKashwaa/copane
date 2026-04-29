"""Tests for ToolResult model and _truncate helper."""

from copane.tools import ToolResult, _truncate


# ---------------------------------------------------------------------------
# ToolResult model
# ---------------------------------------------------------------------------


class TestToolResult:
    def test_defaults(self):
        r = ToolResult(success=True)
        assert r.success is True
        assert r.output == ""
        assert r.error == ""
        assert r.error_type == ""
        assert r.truncated is False

    def test_all_fields(self):
        r = ToolResult(
            success=False,
            output="some output",
            error="something broke",
            error_type="timeout",
            truncated=True,
        )
        assert r.success is False
        assert r.output == "some output"
        assert r.error == "something broke"
        assert r.error_type == "timeout"
        assert r.truncated is True

    def test_str_success(self):
        r = ToolResult(success=True, output="hello")
        assert str(r) == "hello"

    def test_str_error(self):
        r = ToolResult(success=False, error="nope", error_type="oops")
        assert str(r) == "[Error: oops] nope"

    def test_str_truncated(self):
        r = ToolResult(success=True, output="data", truncated=True)
        assert str(r) == "data\n[output truncated]"

    def test_str_error_truncated(self):
        r = ToolResult(
            success=False, error="bad", error_type="whoops", truncated=True
        )
        assert str(r) == "[Error: whoops] bad"

    def test_str_empty_output(self):
        r = ToolResult(success=True)
        assert str(r) == ""


# ---------------------------------------------------------------------------
# _truncate helper
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_short_text(self):
        text, truncated = _truncate("hello", 10)
        assert text == "hello"
        assert truncated is False

    def test_exact_limit(self):
        text, truncated = _truncate("1234567890", 10)
        assert text == "1234567890"
        assert truncated is False

    def test_truncation_occurs(self):
        text, truncated = _truncate("hello world this is long", 10, label="msg")
        assert text == "hello worl\n[... msg truncated to 10 chars]"
        assert truncated is True

    def test_custom_label_in_message(self):
        text, truncated = _truncate("abcdefghijklmnop", 5, label="test")
        assert "test truncated" in text
        assert truncated is True

    def test_empty_string(self):
        text, truncated = _truncate("", 100)
        assert text == ""
        assert truncated is False

    def test_no_limit(self):
        text, truncated = _truncate("a" * 5_000, 10_000)
        assert truncated is False
        assert text == "a" * 5_000
