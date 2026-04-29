"""Tests for the run_command tool."""

from conftest import invoke, parse_result
from copane import tools


class TestRunCommand:
    async def test_simple_echo(self):
        raw = await invoke(tools.run_command, cmd="echo hello world")
        result = parse_result(raw)
        assert result.success is True
        assert "hello world" in result.output
        assert "[exit code: 0]" in result.output

    async def test_non_zero_exit(self):
        raw = await invoke(tools.run_command, cmd="exit 42")
        result = parse_result(raw)
        assert result.success is False
        assert result.error_type == "non_zero_exit"

    async def test_blocked_command(self):
        raw = await invoke(tools.run_command, cmd="rm -rf /")
        result = parse_result(raw)
        assert result.success is False
        assert result.error_type == "blocked_command"

    async def test_blocked_dd(self):
        raw = await invoke(tools.run_command, cmd="dd if=/dev/zero of=/tmp/out bs=1M count=1")
        result = parse_result(raw)
        assert result.success is False
        assert result.error_type == "blocked_command"

    async def test_safe_rm_is_not_blocked(self, tmp_dir):
        """rm on a non-root path should not be blocked."""
        f = tmp_dir / "tempfile"
        f.write_text("data")
        raw = await invoke(tools.run_command, cmd=f"rm {f}")
        result = parse_result(raw)
        assert result.success is True

    async def test_command_with_pipe(self):
        """Shell pipes should work through run_command."""
        raw = await invoke(tools.run_command, cmd="echo hello | wc -c")
        result = parse_result(raw)
        assert result.success is True
        assert "6" in result.output  # "hello\n" = 6 bytes

    async def test_command_with_env_var(self):
        """Environment variables should be expanded by the shell."""
        raw = await invoke(tools.run_command, cmd="echo $HOME")
        result = parse_result(raw)
        assert result.success is True
        assert result.output.strip()
        assert "/" in result.output

    async def test_command_not_found(self):
        raw = await invoke(tools.run_command, cmd="nonexistentcommand12345")
        result = parse_result(raw)
        assert result.success is False
        assert result.error_type in ("command_not_found", "non_zero_exit")
        # Some shells return exit code 127 instead of raising FileNotFoundError

    async def test_stderr_captured(self):
        raw = await invoke(tools.run_command, cmd="echo foo >&2; echo bar")
        result = parse_result(raw)
        assert result.success is True
        assert "foo" in result.output
        assert "bar" in result.output

    async def test_large_output_truncated(self):
        """10k chars should be truncated by the 8k limit."""
        raw = await invoke(tools.run_command, cmd="python3 -c \"print('x' * 10000)\"")
        result = parse_result(raw)
        assert result.success is True
        assert result.truncated is True
        assert "truncated" in result.output

    async def test_timeout(self):
        """A command that sleeps longer than 30s should time out."""
        raw = await invoke(tools.run_command, cmd="sleep 60")
        result = parse_result(raw)
        assert result.success is False
        assert result.error_type == "timeout"
