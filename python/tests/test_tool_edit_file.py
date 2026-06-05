"""Tests for the edit_file tool."""

from conftest import invoke, parse_result
from copane import tools


class TestEditFile:
    async def test_replace_string(self, tmp_dir):
        path = tmp_dir / "target.py"
        path.write_text("def foo():\n    return 1\n\ndef bar():\n    return 2\n")
        raw = await invoke(
            tools.edit_file,
            path=str(path),
            old_string="    return 1",
            new_string="    return 42",
        )
        result = parse_result(raw)
        assert result.success is True
        assert 'replaced 12 chars with 13 chars at line 2' in result.output
        assert path.read_text() == "def foo():\n    return 42\n\ndef bar():\n    return 2\n"

    async def test_not_found(self, tmp_dir):
        path = tmp_dir / "target.py"
        path.write_text("hello world\n")
        raw = await invoke(
            tools.edit_file,
            path=str(path),
            old_string="nonexistent text",
            new_string="replacement",
        )
        result = parse_result(raw)
        assert result.success is False
        assert result.error_type == "not_found"

    async def test_multiple_matches(self, tmp_dir):
        path = tmp_dir / "target.py"
        path.write_text("x = 1\ny = 1\nz = 1\n")
        raw = await invoke(
            tools.edit_file,
            path=str(path),
            old_string="= 1",
            new_string="= 2",
        )
        result = parse_result(raw)
        assert result.success is False
        assert result.error_type == "ambiguous_match"
        assert "3 locations" in result.error

    async def test_file_not_found(self, tmp_dir):
        raw = await invoke(
            tools.edit_file,
            path=str(tmp_dir / "nope.py"),
            old_string="foo",
            new_string="bar",
        )
        result = parse_result(raw)
        assert result.success is False
        assert result.error_type == "file_not_found"

    async def test_empty_old_string(self, tmp_dir):
        path = tmp_dir / "target.py"
        path.write_text("hello\n")
        raw = await invoke(
            tools.edit_file,
            path=str(path),
            old_string="",
            new_string="world",
        )
        result = parse_result(raw)
        assert result.success is False
        assert result.error_type == "invalid_argument"

    async def test_line_number_accurate(self, tmp_dir):
        """The line number in the output should reflect the actual file line."""
        path = tmp_dir / "target.py"
        path.write_text("# comment\n\n\ndef main():\n    pass\n")
        raw = await invoke(
            tools.edit_file,
            path=str(path),
            old_string="    pass",
            new_string="    return 0",
        )
        result = parse_result(raw)
        assert result.success is True
        assert "at line 5" in result.output
