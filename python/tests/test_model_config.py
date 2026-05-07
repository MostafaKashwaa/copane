"""Tests for ModelConfig — pure file-system CRUD, no SDK/network."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from copane.model_config import ModelConfig


# -------------------------------------------------------------------
# helpers
# -------------------------------------------------------------------


@pytest.fixture
def temp_config():
    """ModelConfig pointed at a temp directory (isolates from real config)."""
    with tempfile.TemporaryDirectory() as d:
        with patch.object(
            ModelConfig, "__init__", autospec=True, return_value=None
        ):
            mc = ModelConfig.__new__(ModelConfig)
            mc.config_dir = Path(d)
            mc.config_file = Path(d) / "model_config.json"
            mc.default_config = {
                "selected_model": "deepseek-chat",
                "available_models": {
                    "deepseek-chat": {
                        "type": "api",
                        "base_url": "https://api.deepseek.com/v1",
                        "model_name": "deepseek-chat",
                        "env_key": "DEEPSEEK_API_KEY",
                        "description": "DeepSeek Chat (Default)",
                    },
                    "gpt-4o": {
                        "type": "api",
                        "base_url": "https://api.openai.com/v1",
                        "model_name": "gpt-4o",
                        "env_key": "OPENAI_API_KEY",
                        "description": "OpenAI GPT-4o",
                    },
                },
            }
            mc._ensure_config()
            yield mc


# -------------------------------------------------------------------
# initialisation & defaults
# -------------------------------------------------------------------


class TestInitialisation:
    def test_ensure_config_creates_dir_and_file(self, temp_config):
        assert temp_config.config_dir.exists()
        assert temp_config.config_file.exists()

    def test_default_selected_model(self, temp_config):
        assert temp_config.get_selected_model() == "deepseek-chat"

    def test_default_available_models(self, temp_config):
        models = temp_config.get_available_models()
        assert "deepseek-chat" in models
        assert "gpt-4o" in models

    def test_recover_from_missing_file(self, temp_config):
        temp_config.config_file.unlink()
        config = temp_config.load_config()
        assert config == temp_config.default_config

    def test_recover_from_corrupt_json(self, temp_config):
        temp_config.config_file.write_text("not valid json {{{")
        config = temp_config.load_config()
        assert config == temp_config.default_config


# -------------------------------------------------------------------
# CRUD operations
# -------------------------------------------------------------------


class TestCRUD:
    def test_load_save_roundtrip(self, temp_config):
        original = temp_config.load_config()
        temp_config.save_config(original)
        reloaded = temp_config.load_config()
        assert reloaded == original

    def test_set_selected_model(self, temp_config):
        temp_config.set_selected_model("gpt-4o")
        assert temp_config.get_selected_model() == "gpt-4o"
        # persist across reload
        reloaded = temp_config.load_config()
        assert reloaded["selected_model"] == "gpt-4o"

    def test_set_selected_model_invalid(self, temp_config):
        with pytest.raises(ValueError, match="not found"):
            temp_config.set_selected_model("nonexistent-model")

    def test_add_custom_model(self, temp_config):
        temp_config.add_custom_model(
            "claude",
            {
                "type": "api",
                "base_url": "https://api.anthropic.com/v1",
                "model_name": "claude-3",
                "env_key": "ANTHROPIC_API_KEY",
                "description": "Claude",
            },
        )
        models = temp_config.get_available_models()
        assert "claude" in models
        assert models["claude"]["model_name"] == "claude-3"

    def test_remove_model(self, temp_config):
        temp_config.add_custom_model("test-model", {"type": "api", "model_name": "test"})
        assert "test-model" in temp_config.get_available_models()
        temp_config.remove_model("test-model")
        assert "test-model" not in temp_config.get_available_models()

    def test_remove_nonexistent_model_no_error(self, temp_config):
        # Should not raise
        temp_config.remove_model("does-not-exist")

    def test_remove_selected_model_falls_back(self, temp_config):
        temp_config.set_selected_model("gpt-4o")
        temp_config.remove_model("gpt-4o")
        assert temp_config.get_selected_model() == "deepseek-chat"

    def test_remove_last_model_keeps_default_selected(self, temp_config):
        # Remove deepseek but gpt-4o still exists
        temp_config.remove_model("deepseek-chat")
        assert temp_config.get_selected_model() == "deepseek-chat"  # not in list, but returned as default

    def test_get_available_models_is_copy(self, temp_config):
        models = temp_config.get_available_models()
        models["hacked"] = {}
        # should not persist
        assert "hacked" not in temp_config.get_available_models()
