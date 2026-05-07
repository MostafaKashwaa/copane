"""Model configuration management for copane.

Provides ``ModelConfig`` — a self-contained CRUD class for AI model
configurations, backed by ``~/.config/tmux-agent/model_config.json``.
"""

import json
from pathlib import Path
from typing import Any, Dict


class ModelConfig:
    """Configuration for AI models with professional management."""

    def __init__(self):
        self.config_dir = Path.home() / ".config" / "tmux-agent"
        self.config_file = self.config_dir / "model_config.json"
        self.default_config = {
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
                "local-ollama": {
                    "type": "local",
                    "base_url": "http://localhost:11434/v1",
                    "model_name": "gemma4:26b",
                    "env_key": "",
                    "description": "Local Ollama (gemma4:26b)",
                },
            },
        }
        self._ensure_config()

    def _ensure_config(self):
        """Ensure configuration directory and file exist."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        if not self.config_file.exists():
            self.save_config(self.default_config)

    def load_config(self) -> Dict[str, Any]:
        """Load configuration from file."""
        try:
            with open(self.config_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return self.default_config

    def save_config(self, config: Dict[str, Any]):
        """Save configuration to file."""
        with open(self.config_file, "w") as f:
            json.dump(config, f, indent=2)

    def get_selected_model(self) -> str:
        """Get the currently selected model."""
        config = self.load_config()
        return config.get("selected_model", "deepseek-chat")

    def set_selected_model(self, model_key: str):
        """Set the selected model."""
        config = self.load_config()
        if model_key in config.get("available_models", {}):
            config["selected_model"] = model_key
            self.save_config(config)
        else:
            raise ValueError(f"Model '{model_key}' not found in available models")

    def get_available_models(self) -> Dict[str, Dict[str, Any]]:
        """Get all available models."""
        config = self.load_config()
        return config.get("available_models", {})

    def add_custom_model(self, key: str, model_config: Dict[str, Any]):
        """Add a custom model configuration."""
        config = self.load_config()
        config["available_models"][key] = model_config
        self.save_config(config)

    def remove_model(self, key: str):
        """Remove a model configuration."""
        config = self.load_config()
        if key in config.get("available_models", {}):
            del config["available_models"][key]
            # If we're removing the selected model, fall back to default
            if config.get("selected_model") == key:
                config["selected_model"] = "deepseek-chat"
            self.save_config(config)
