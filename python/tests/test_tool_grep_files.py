"""Tests for the grep_files tool."""

from conftest import invoke, parse_result
from copane import tools


class TestGrepFiles:
    async def test_basic_grep(self, tmp_dir):
        (tmp_dir / "a.txt").write_text("hello world\nfoo bar\n")
        (tmp_dir / "b.txt").write_text("foo baz\nqux quux\n")
        raw = await invoke(tools.grep_files, pattern="foo", path=str(tmp_dir), file_glob="*.txt")
        result = parse_result(raw)
        assert result.success is True
        assert "a.txt" in result.output
        assert "b.txt" in result.output

    async def test_no_matches(self, tmp_dir):
        (tmp_dir / "a.txt").write_text("hello\n")
        raw = await invoke(tools.grep_files, pattern="zzzzz", path=str(tmp_dir))
        result = parse_result(raw)
        assert result.success is False
        assert result.error_type == "no_matches"

    async def test_nonexistent_path(self):
        raw = await invoke(tools.grep_files, pattern="foo", path="/nonexistent")
        result = parse_result(raw)
        assert result.success is False

    async def test_single_file_grep(self, tmp_dir):
        f = tmp_dir / "data.py"
        f.write_text("import os\nimport sys\n")
        raw = await invoke(tools.grep_files, pattern="import", path=str(f))
        result = parse_result(raw)
        assert result.success is True
        # grep output shows relative path from the tmp_dir root
        assert "import os" in result.output
        assert "import sys" in result.output

    async def test_regex_pattern(self, tmp_dir):
        (tmp_dir / "test.txt").write_text("abc123\ndef456\nabc789\n")
        # Use ERE-compatible pattern (grep -E does not support \d)
        raw = await invoke(tools.grep_files, pattern="abc[0-9]+", path=str(tmp_dir), file_glob="*.txt")
        result = parse_result(raw)
        assert result.success is True
        assert "abc123" in result.output
        assert "abc789" in result.output
        assert "def456" not in result.output

    async def test_large_output_truncated(self, tmp_dir):
        """Generate enough matches to trigger the 5k truncation limit."""
        content = "\n".join(f"match_{i}" for i in range(5000))
        f = tmp_dir / "big.txt"
        f.write_text(content)
        raw = await invoke(tools.grep_files, pattern="match_", path=str(tmp_dir))
        result = parse_result(raw)
        assert result.success is True
        assert result.truncated is True

    async def test_special_chars_safe(self, tmp_dir):
        """Path or patterns with spaces/special chars should be handled."""
        subdir = tmp_dir / "my dir"
        subdir.mkdir()
        f = subdir / "test.txt"
        f.write_text("hello world\n")
        raw = await invoke(tools.grep_files, pattern="hello", path=str(subdir))
        result = parse_result(raw)
        assert result.success is True
        assert "hello" in result.output
