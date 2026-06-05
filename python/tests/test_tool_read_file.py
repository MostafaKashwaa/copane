"""Tests for the read_file tool."""

from copane import tools
from conftest import invoke, parse_result


class TestReadFile:
    async def test_read_full_file(self, sample_file):
        raw = await invoke(tools.read_file, path=str(sample_file))
        result = parse_result(raw)
        assert result.success is True
        # Output includes line numbers, right-padded.  5-line file →
        # max line number is 1 digit, width = max(3, 1) = 3 → "  1  line1\n"
        assert result.output == (
            "  1  line1\n"
            "  2  line2\n"
            "  3  line3\n"
            "  4  line4\n"
            "  5  line5\n"
        )

    async def test_read_line_range(self, sample_file):
        raw = await invoke(tools.read_file, path=str(sample_file), start_line=2, end_line=4)
        result = parse_result(raw)
        assert result.success is True
        assert result.output == "  2  line2\n  3  line3\n  4  line4\n"

    async def test_read_single_line(self, sample_file):
        raw = await invoke(tools.read_file, path=str(sample_file), start_line=3, end_line=3)
        result = parse_result(raw)
        assert result.success is True
        assert result.output == "  3  line3\n"

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
        # Empty file with defaults (start_line=1, end_line=0) should succeed
        # and return empty output.
        assert result.success is True
        assert result.output == ""

    async def test_empty_file_explicit_start_end(self, tmp_dir):
        path = tmp_dir / "empty2.txt"
        path.write_text("")
        raw = await invoke(tools.read_file, path=str(path), start_line=1, end_line=1)
        result = parse_result(raw)
        assert result.success is True
        assert result.output == ""

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
        assert result.output == "  3  line3\n  4  line4\n  5  line5\n"

    async def test_line_number_width_expands(self, tmp_dir):
        """Line numbers pad to the width required for the last line."""
        lines = [f"line{i}\n" for i in range(1, 101)]  # 100 lines
        path = tmp_dir / "big.txt"
        path.write_text("".join(lines))
        raw = await invoke(tools.read_file, path=str(path))
        result = parse_result(raw)
        assert result.success is True
        # First line should be 3-digit padded (100 lines → width=3)
        first, rest = result.output.split("\n", 1)
        assert first.startswith("  1  line1")
        # Line 100 should be 3-digit: "100  line100"
        assert "100  line100" in result.output
