"""Tests for the write_file tool."""

from unittest.mock import patch

from conftest import invoke, parse_result
from copane import tools


class TestWriteFile:
    async def test_accept_write(self, tmp_dir):
        path = tmp_dir / "newfile.txt"
        with patch.object(tools, "_confirm_session", None):
            with patch("builtins.input", return_value="y"):
                raw = await invoke(tools.write_file, path=str(path), content="hello world\n")
        result = parse_result(raw)
        assert result.success is True
        assert path.read_text() == "hello world\n"

    async def test_cancel_write(self, tmp_dir):
        path = tmp_dir / "cancelled.txt"
        with patch.object(tools, "_confirm_session", None):
            with patch("builtins.input", return_value="n"):
                raw = await invoke(tools.write_file, path=str(path), content="should not appear")
        result = parse_result(raw)
        assert result.success is False
        assert result.error_type == "write_cancelled"
        assert not path.exists()

    async def test_always_allow(self, tmp_dir):
        path = tmp_dir / "always.txt"
        with patch.object(tools, "_confirm_session", None):
            with patch("builtins.input", return_value="a"):
                raw = await invoke(tools.write_file, path=str(path), content="hello")
        result = parse_result(raw)
        assert result.success is True
        assert "always-allowed" in result.output
        assert path.read_text() == "hello"

    async def test_overwrite_existing(self, tmp_dir):
        path = tmp_dir / "existing.txt"
        path.write_text("old content")
        with patch.object(tools, "_confirm_session", None):
            with patch("builtins.input", return_value="y"):
                raw = await invoke(tools.write_file, path=str(path), content="new content")
        result = parse_result(raw)
        assert result.success is True
        assert path.read_text() == "new content"

    async def test_empty_content(self, tmp_dir):
        path = tmp_dir / "empty.txt"
        with patch.object(tools, "_confirm_session", None):
            with patch("builtins.input", return_value="y"):
                raw = await invoke(tools.write_file, path=str(path), content="")
        result = parse_result(raw)
        assert result.success is True
        assert path.read_text() == ""
        assert path.exists()
