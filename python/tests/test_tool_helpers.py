"""Tests for _is_dangerous and _format_diff helpers."""

import os
import tempfile

from copane.tools import _is_dangerous, _format_diff


# ---------------------------------------------------------------------------
# _is_dangerous
# ---------------------------------------------------------------------------


class TestIsDangerous:
    def test_rm_rf_root(self):
        assert _is_dangerous("rm -rf /") is not None

    def test_rm_rf_home(self):
        assert _is_dangerous("rm -rf ~") is not None

    def test_rm_rf_root_with_flags(self):
        assert _is_dangerous("something; rm -rf /") is not None

    def test_dd_if_dev_zero(self):
        assert _is_dangerous("dd if=/dev/zero of=/dev/sda") is not None

    def test_redirect_to_dev(self):
        assert _is_dangerous("echo foo > /dev/sda") is not None

    def test_mkfs(self):
        assert _is_dangerous("mkfs.ext4 /dev/sda1") is not None

    def test_fork_bomb(self):
        assert _is_dangerous(":(){ :|:& };:") is not None

    def test_chmod_0000(self):
        assert _is_dangerous("chmod -R 0000 /") is not None

    def test_mv_to_dev_null(self):
        assert _is_dangerous("mv ~ /dev/null") is not None

    def test_safe_command(self):
        assert _is_dangerous("echo hello") is None

    def test_ls(self):
        assert _is_dangerous("ls -la") is None

    def test_git_diff(self):
        assert _is_dangerous("git diff") is None

    def test_case_insensitivity_rm(self):
        assert _is_dangerous("RM -RF /") is not None

    def test_nested_rm(self):
        assert _is_dangerous("find . -exec rm -rf {} +") is None  # no leading /

    def test_false_positive_rm(self):
        # A file named "rm" is fine
        assert _is_dangerous("cat rm") is None

    def test_dd_safe(self):
        # Any dd with if= is blocked — there's no "safe" dd
        assert _is_dangerous("dd if=/dev/random of=./output.bin") is not None


# ---------------------------------------------------------------------------
# _format_diff
# ---------------------------------------------------------------------------


class TestFormatDiff:
    def test_new_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "new.txt")
            result = _format_diff(path, "hello world")
            assert "(new file)" in result
            assert "hello world" in result

    def test_existing_file_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "existing.txt")
            with open(path, "w") as f:
                f.write("same content\n")
            result = _format_diff(path, "same content\n")
            # Unified diff for identical content produces empty string
            assert result == ""

    def test_existing_file_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "existing.txt")
            with open(path, "w") as f:
                f.write("old line\n")
            result = _format_diff(path, "new line\n")
            assert "-old line" in result
            assert "+new line" in result

    def test_nonexistent_path(self):
        result = _format_diff("/nonexistent/path/file.txt", "content")
        assert "(new file)" in result
        assert "content" in result

    def test_multiline_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "multi.txt")
            with open(path, "w") as f:
                f.write("line1\nline2\nline3\n")
            result = _format_diff(path, "line1\nchanged2\nline3\n")
            assert "-line2" in result
            assert "+changed2" in result
