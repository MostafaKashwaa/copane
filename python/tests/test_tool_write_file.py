"""Tests for the write_file tool."""

from conftest import invoke, parse_result
from copane import tools


class TestWriteFile:
    async def test_accept_write(self, tmp_dir):
        path = tmp_dir / "newfile.txt"
        raw = await invoke(tools.write_file, path=str(path), content="hello world\n")
        result = parse_result(raw)
        assert result.success is True
        assert result.output == f"Wrote 12 chars to {path}"
        assert path.read_text() == "hello world\n"

    async def test_overwrite_existing(self, tmp_dir):
        path = tmp_dir / "existing.txt"
        path.write_text("old content")
        raw = await invoke(tools.write_file, path=str(path), content="new content")
        result = parse_result(raw)
        assert result.success is True
        assert path.read_text() == "new content"

    async def test_empty_content(self, tmp_dir):
        path = tmp_dir / "empty.txt"
        raw = await invoke(tools.write_file, path=str(path), content="")
        result = parse_result(raw)
        assert result.success is True
        assert path.read_text() == ""
        assert path.exists()
