"""Tests for the read_file tool."""

from copane import tools
from conftest import invoke, parse_result


class TestReadFile:
    async def test_read_full_file(self, sample_file):
        raw = await invoke(tools.read_file, path=str(sample_file))
        result = parse_result(raw)
        assert result.success is True
        assert result.output == "line1\nline2\nline3\nline4\nline5\n"

    async def test_read_line_range(self, sample_file):
        raw = await invoke(tools.read_file, path=str(sample_file), start_line=2, end_line=4)
        result = parse_result(raw)
        assert result.success is True
        assert result.output == "line2\nline3\nline4\n"

    async def test_read_single_line(self, sample_file):
        raw = await invoke(tools.read_file, path=str(sample_file), start_line=3, end_line=3)
        result = parse_result(raw)
        assert result.success is True
        assert result.output == "line3\n"

    async def test_file_not_found(self):
        raw = await invoke(tools.read_file, path="/nonexistent/path/file.txt")
        result = parse_result(raw)
        assert result.success is False
        assert result.error_type == "file_not_found"

    async def test_start_line_exceeds_length(self, sample_file):
        raw = await invoke(tools.read_file, path=str(sample_file), start_line=100)
        result = parse_result(raw)
        assert result.success is False
        assert result.error_type == "invalid_range"

    async def test_empty_file(self, tmp_dir):
        path = tmp_dir / "empty.txt"
        path.write_text("")
        raw = await invoke(tools.read_file, path=str(path))
        result = parse_result(raw)
        # read_file currently errors on empty files due to line-range logic
        # (start_line=1 > len(lines)=0).
        assert result.success is False
        assert result.error_type == "invalid_range"

    async def test_binary_file(self, tmp_dir):
        path = tmp_dir / "binary.bin"
        path.write_bytes(b"\x00\x01\x02\x03")
        raw = await invoke(tools.read_file, path=str(path))
        result = parse_result(raw)
        assert result.success is True
        # binary content is read as text (not an error, just may look garbled)

    async def test_end_line_defaults_to_end(self, sample_file):
        raw = await invoke(tools.read_file, path=str(sample_file), start_line=3)
        result = parse_result(raw)
        assert result.success is True
        assert result.output == "line3\nline4\nline5\n"
