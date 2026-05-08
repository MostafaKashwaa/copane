"""Tests for ModelProvider — model discovery, status checks, and Agent creation.

Pure unit tests with mocked SDK objects. No live LLM, no network calls.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from copane.model_config import ModelConfig
from copane.model_provider import ModelProvider


# -------------------------------------------------------------------
# fixtures
# -------------------------------------------------------------------


@pytest.fixture
def mc():
    """A ModelConfig with a known test configuration."""
    mock = MagicMock(spec=ModelConfig)
    mock.get_selected_model.return_value = "deepseek-chat"
    mock.get_available_models.return_value = {
        "deepseek-chat": {
            "type": "api",
            "base_url": "https://api.deepseek.com/v1",
            "model_name": "deepseek-chat",
            "env_key": "DEEPSEEK_API_KEY",
            "description": "DeepSeek Chat (Default)",
        },
        "gemma4": {
            "type": "local",
            "base_url": "http://localhost:11434/v1",
            "model_name": "gemma4",
            "env_key": "",
            "description": "Local Gemma 4 via Ollama",
        },
        "gpt-4o": {
            "type": "api",
            "base_url": "https://api.openai.com/v1",
            "model_name": "gpt-4o",
            "env_key": "OPENAI_API_KEY",
            "description": "OpenAI GPT-4o",
        },
        "no-type-model": {
            "base_url": "http://x",
            "model_name": "weird",
        },
    }
    return mock


@pytest.fixture
def provider(mc):
    """A ModelProvider wired to a mock ModelConfig."""
    return ModelProvider(model_config=mc)


@pytest.fixture
def mock_tools():
    """A list of mock Tool objects with .name attributes."""
    t1 = MagicMock()
    t1.name = "read_file"
    t2 = MagicMock()
    t2.name = "run_command"
    return [t1, t2]


# ── helper for injecting a fake httpx module ─────────────────────────


def _inject_httpx(**kwargs) -> MagicMock:
    """Push a mock httpx module into sys.modules and return it.

    The mock is removed automatically when the caller's ``with``
    block exits (via ``patch.dict`` cleanup).
    """
    mock_httpx = MagicMock(**kwargs)
    return patch.dict(sys.modules, {"httpx": mock_httpx}), mock_httpx


# -------------------------------------------------------------------
# 1. __init__
# -------------------------------------------------------------------


class TestInit:
    def test_accepts_custom_model_config(self, mc):
        p = ModelProvider(model_config=mc)
        assert p.model_config is mc

    def test_default_creates_model_config(self):
        p = ModelProvider()
        assert isinstance(p.model_config, ModelConfig)


# -------------------------------------------------------------------
# 2. check_model_status (static)
# -------------------------------------------------------------------


class TestCheckModelStatus:
    # ── local model paths ──

    def test_local_available(self):
        cleanup, mock_httpx = _inject_httpx()
        mock_httpx.get.return_value.status_code = 200
        with cleanup:
            result = ModelProvider.check_model_status(
                {"type": "local", "base_url": "http://localhost:11434/v1"}
            )
        assert result == "available"
        mock_httpx.get.assert_called_once_with(
            "http://localhost:11434/v1/models", timeout=2
        )

    def test_local_unreachable_non_200(self):
        cleanup, mock_httpx = _inject_httpx()
        mock_httpx.get.return_value.status_code = 404
        with cleanup:
            result = ModelProvider.check_model_status(
                {"type": "local", "base_url": "http://localhost:11434/v1"}
            )
        assert result == "unreachable (try running 'ollama serve' or correcting base_url)"

    def test_local_httpx_not_installed(self):
        # Block the import of httpx so 'import httpx' raises ImportError inside check_model_status.
        _real_import = __import__

        def _block_httpx(name, *args, **kwargs):
            if name == "httpx":
                raise ImportError("No module named 'httpx'")
            return _real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_block_httpx):
            result = ModelProvider.check_model_status(
                {"type": "local", "base_url": "http://localhost:11434/v1"}
            )
        assert result == "Cannot check (httpx not installed)"

    @pytest.mark.parametrize(
        "exc",
        [
            Exception("timeout"),
            OSError("connection refused"),
        ],
    )
    def test_local_httpx_exception(self, exc):
        cleanup, mock_httpx = _inject_httpx()
        mock_httpx.get.side_effect = exc
        with cleanup:
            result = ModelProvider.check_model_status(
                {"type": "local", "base_url": "http://localhost:11434/v1"}
            )
        assert result == "unreachable"

    def test_local_missing_base_url(self):
        result = ModelProvider.check_model_status({"type": "local"})
        assert result == "unavailable (local model missing base_url)"

    def test_local_empty_base_url_falsy(self):
        result = ModelProvider.check_model_status(
            {"type": "local", "base_url": ""}
        )
        assert result == "unavailable (local model missing base_url)"

    # ── API model paths ──

    def test_api_configured(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-1234")
        result = ModelProvider.check_model_status(
            {"type": "api", "env_key": "DEEPSEEK_API_KEY"}
        )
        assert result == "configured"

    def test_api_missing_key(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        result = ModelProvider.check_model_status(
            {"type": "api", "env_key": "DEEPSEEK_API_KEY"}
        )
        assert result == "missing_api_key"

    def test_unknown_type_no_env_key(self):
        result = ModelProvider.check_model_status({})
        assert result == "unknown"

    def test_api_type_missing_env_key_in_dict(self):
        """type=api but no env_key in dict → falls through to unknown."""
        result = ModelProvider.check_model_status({"type": "api"})
        assert result == "unknown"


# -------------------------------------------------------------------
# 3. get_model_info
# -------------------------------------------------------------------


class TestGetModelInfo:
    def test_returns_all_expected_keys(self, provider):
        info = provider.get_model_info()
        for key in ("key", "name", "description", "type", "base_url", "env_key", "status"):
            assert key in info

    def test_selected_model_key_matches(self, provider, mc):
        info = provider.get_model_info()
        assert info["key"] == mc.get_selected_model()

    def test_model_not_in_available_defaults(self, provider, mc):
        mc.get_selected_model.return_value = "nonexistent"
        info = provider.get_model_info()
        assert info["key"] == "nonexistent"
        assert info["name"] == "nonexistent"  # fallback to key
        assert info["description"] == "Unknown model"
        assert info["type"] == "unknown"

    def test_status_called_with_model_info(self, provider, mc):
        with patch.object(ModelProvider, "check_model_status") as mock_check:
            mock_check.return_value = "configured"
            info = provider.get_model_info()
            mock_check.assert_called_once()
            called_with = mock_check.call_args[0][0]
            assert called_with["model_name"] == "deepseek-chat"
        assert info["status"] == "configured"

    def test_description_falls_back_to_unknown(self, provider, mc):
        mc.get_available_models.return_value["deepseek-chat"].pop(
            "description", None)
        info = provider.get_model_info()
        assert info["description"] == "Unknown model"

    def test_name_falls_back_to_key(self, provider, mc):
        mc.get_available_models.return_value["deepseek-chat"].pop(
            "model_name", None)
        info = provider.get_model_info()
        assert info["name"] == "deepseek-chat"  # falls back to key


# -------------------------------------------------------------------
# 4. list_available_models
# -------------------------------------------------------------------


class TestListAvailableModels:
    def test_returns_dict_keyed_by_model_keys(self, provider, mc):
        result = provider.list_available_models()
        assert set(result.keys()) == set(mc.get_available_models().keys())

    def test_each_entry_has_required_fields(self, provider):
        result = provider.list_available_models()
        for key, entry in result.items():
            for field in ("name", "description", "type", "status", "is_selected"):
                assert field in entry, f"{field} missing from {key}"

    def test_is_selected_true_for_exactly_one(self, provider, mc):
        result = provider.list_available_models()
        selected = [k for k, v in result.items() if v["is_selected"]]
        assert len(selected) == 1
        assert selected[0] == mc.get_selected_model()

    def test_empty_models_returns_empty_dict(self, mc):
        mc.get_available_models.return_value = {}
        provider = ModelProvider(model_config=mc)
        result = provider.list_available_models()
        assert result == {}

    def test_status_checked_for_each_model(self, provider, mc):
        with patch.object(ModelProvider, "check_model_status") as mock_check:
            mock_check.return_value = "ok"
            provider.list_available_models()
            model_count = len(mc.get_available_models())
            assert mock_check.call_count == model_count

    def test_selected_not_in_available_none_selected(self, provider, mc):
        mc.get_selected_model.return_value = "phantom-model"
        result = provider.list_available_models()
        selected = [k for k, v in result.items() if v["is_selected"]]
        assert len(selected) == 0


# -------------------------------------------------------------------
# 5. switch_model
# -------------------------------------------------------------------


class TestSwitchModel:
    def test_valid_key_calls_set_selected_model(self, provider, mc):
        provider.switch_model("gpt-4o")
        mc.set_selected_model.assert_called_once_with("gpt-4o")

    def test_invalid_key_raises_valueerror(self, provider, mc):
        with pytest.raises(ValueError, match="not found"):
            provider.switch_model("nonexistent-model")

    def test_switch_to_same_model_works(self, provider, mc):
        provider.switch_model("deepseek-chat")
        mc.set_selected_model.assert_called_once_with("deepseek-chat")

    def test_empty_available_models_raises(self, mc):
        mc.get_available_models.return_value = {}
        provider = ModelProvider(model_config=mc)
        with pytest.raises(ValueError, match="not found"):
            provider.switch_model("anything")


# -------------------------------------------------------------------
# 6. create_agent
# -------------------------------------------------------------------


class TestCreateAgent:
    # ── API type ──

    def test_api_type_creates_client_with_api_key(
        self, provider, mc, mock_tools, monkeypatch
    ):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key")

        with (
            patch("copane.model_provider.AsyncOpenAI") as mock_client_cls,
            patch("copane.model_provider.OpenAIChatCompletionsModel") as mock_model_cls,
            patch("copane.model_provider.Agent") as mock_agent_cls,
        ):
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_model = MagicMock()
            mock_model_cls.return_value = mock_model
            mock_agent_cls.return_value = MagicMock()

            provider.create_agent(mock_tools, "test-agent")

            mock_client_cls.assert_called_once_with(
                base_url="https://api.deepseek.com/v1",
                api_key="sk-test-key",
            )
            mock_model_cls.assert_called_once_with(
                model="deepseek-chat",
                openai_client=mock_client,
            )
            mock_agent_cls.assert_called_once()
            _, kwargs = mock_agent_cls.call_args
            assert kwargs["name"] == "test-agent"
            assert kwargs["tools"] == mock_tools
            assert kwargs["model"] is mock_model

    def test_api_type_missing_env_key_raises(self, provider, mock_tools, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        with (
            patch("copane.model_provider.AsyncOpenAI"),
            patch("copane.model_provider.OpenAIChatCompletionsModel"),
            patch("copane.model_provider.Agent"),
        ):
            with pytest.raises(ValueError, match="API key"):
                provider.create_agent(mock_tools, "test-agent")

    def test_api_type_empty_env_key_raises(self, provider, mock_tools, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "")
        with (
            patch("copane.model_provider.AsyncOpenAI"),
            patch("copane.model_provider.OpenAIChatCompletionsModel"),
            patch("copane.model_provider.Agent"),
        ):
            with pytest.raises(ValueError, match="API key"):
                provider.create_agent(mock_tools, "test-agent")

    # ── Local type ──

    def test_local_type_creates_client_with_empty_key(
        self, provider, mc, mock_tools
    ):
        mc.get_selected_model.return_value = "gemma4"

        with (
            patch("copane.model_provider.AsyncOpenAI") as mock_client_cls,
            patch("copane.model_provider.OpenAIChatCompletionsModel") as mock_model_cls,
            patch("copane.model_provider.Agent") as mock_agent_cls,
        ):
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_model = MagicMock()
            mock_model_cls.return_value = mock_model
            mock_agent_cls.return_value = MagicMock()

            provider.create_agent(mock_tools, "test-agent")

            mock_client_cls.assert_called_once_with(
                base_url="http://localhost:11434/v1",
                api_key="",
            )

    # ── Unknown / missing ──

    def test_unknown_type_raises(self, provider, mc, mock_tools):
        mc.get_selected_model.return_value = "no-type-model"

        with (
            patch("copane.model_provider.AsyncOpenAI"),
            patch("copane.model_provider.OpenAIChatCompletionsModel"),
            patch("copane.model_provider.Agent"),
        ):
            with pytest.raises(ValueError, match="Unknown model type"):
                provider.create_agent(mock_tools, "test-agent")

    def test_missing_config_for_selected_model_raises(
        self, provider, mc, mock_tools
    ):
        mc.get_selected_model.return_value = "missing-model"

        with (
            patch("copane.model_provider.AsyncOpenAI"),
            patch("copane.model_provider.OpenAIChatCompletionsModel"),
            patch("copane.model_provider.Agent"),
        ):
            with pytest.raises(ValueError, match="not found"):
                provider.create_agent(mock_tools, "test-agent")

    # ── Agent construction details ──

    def test_creates_agent_with_correct_tools(
        self, provider, mock_tools, monkeypatch
    ):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

        with (
            patch("copane.model_provider.AsyncOpenAI"),
            patch("copane.model_provider.OpenAIChatCompletionsModel"),
            patch("copane.model_provider.Agent") as mock_agent_cls,
        ):
            provider.create_agent(mock_tools, "test-agent")
            _, kwargs = mock_agent_cls.call_args
            assert kwargs["tools"] == mock_tools

    def test_creates_agent_with_correct_model(
        self, provider, mock_tools, monkeypatch
    ):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

        with (
            patch("copane.model_provider.AsyncOpenAI"),
            patch("copane.model_provider.OpenAIChatCompletionsModel") as mock_model_cls,
            patch("copane.model_provider.Agent") as mock_agent_cls,
        ):
            mock_model = MagicMock()
            mock_model_cls.return_value = mock_model
            provider.create_agent(mock_tools, "test-agent")
            _, kwargs = mock_agent_cls.call_args
            assert kwargs["model"] is mock_model

    def test_creates_agent_with_correct_name(
        self, provider, mock_tools, monkeypatch
    ):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

        with (
            patch("copane.model_provider.AsyncOpenAI"),
            patch("copane.model_provider.OpenAIChatCompletionsModel"),
            patch("copane.model_provider.Agent") as mock_agent_cls,
        ):
            provider.create_agent(mock_tools, "my-custom-agent")
            _, kwargs = mock_agent_cls.call_args
            assert kwargs["name"] == "my-custom-agent"


# -------------------------------------------------------------------
# 7. Edge cases
# -------------------------------------------------------------------


class TestEdgeCases:
    def test_local_with_only_type_no_base_url(self):
        result = ModelProvider.check_model_status({"type": "local"})
        assert result == "unavailable (local model missing base_url)"

    def test_api_with_env_key_but_no_type_field(self, monkeypatch):
        """env_key set but no type field → hits the `if env_key:` branch."""
        monkeypatch.setenv("SOME_KEY", "some-value")
        result = ModelProvider.check_model_status({"env_key": "SOME_KEY"})
        assert result == "configured"

    def test_api_with_env_key_but_no_type_field_missing_key(self, monkeypatch):
        monkeypatch.delenv("SOME_KEY", raising=False)
        result = ModelProvider.check_model_status({"env_key": "SOME_KEY"})
        assert result == "missing_api_key"

    def test_check_model_status_empty_dict(self):
        result = ModelProvider.check_model_status({})
        assert result == "unknown"
