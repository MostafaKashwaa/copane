"""Tests for the get_current_dir tool."""

import os

from conftest import invoke, parse_result
from copane import tools


class TestGetCurrentDir:
    async def test_returns_valid_directory(self):
        raw = await invoke(tools.get_current_dir)
        result = parse_result(raw)
        assert result.success is True
        assert os.path.isdir(result.output)

    async def test_matches_os_getcwd(self):
        raw = await invoke(tools.get_current_dir)
        result = parse_result(raw)
        assert result.output == os.getcwd()

    async def test_changes_with_chdir(self, tmp_dir):
        old = os.getcwd()
        try:
            os.chdir(str(tmp_dir))
            raw = await invoke(tools.get_current_dir)
            result = parse_result(raw)
            assert result.output == str(tmp_dir)
        finally:
            os.chdir(old)

    async def test_is_absolute_path(self):
        raw = await invoke(tools.get_current_dir)
        result = parse_result(raw)
        assert os.path.isabs(result.output)
