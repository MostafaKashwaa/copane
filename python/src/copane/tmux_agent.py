#!/usr/bin/env python3
"""
tmux-agent: AI agent configuration for terminal-based coding assistance.
Enhanced with professional model selection and configuration management.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any

from agents import Agent, OpenAIChatCompletionsModel, RawResponsesStreamEvent, RunItemStreamEvent, Tool, Runner
from openai import AsyncOpenAI
from openai.types.responses import ResponseReasoningTextDeltaEvent, ResponseTextDeltaEvent

from langsmith import traceable

from copane.tools import (
    read_file,
    run_command,
    grep_files,
    list_files,
    write_file,
    get_current_dir
)


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
                    "description": "DeepSeek Chat (Default)"
                },
                "gpt-4o": {
                    "type": "api",
                    "base_url": "https://api.openai.com/v1",
                    "model_name": "gpt-4o",
                    "env_key": "OPENAI_API_KEY",
                    "description": "OpenAI GPT-4o"
                },
                "local-ollama": {
                    "type": "local",
                    "base_url": "http://localhost:11434/v1",
                    "model_name": "gemma4:26b",
                    "env_key": "",
                    "description": "Local Ollama (gemma4:26b)"
                }
            }
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
            with open(self.config_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return self.default_config

    def save_config(self, config: Dict[str, Any]):
        """Save configuration to file."""
        with open(self.config_file, 'w') as f:
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
            raise ValueError(
                f"Model '{model_key}' not found in available models")

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


class TmuxAgent:
    """TmuxAgent is an AI assistant designed to help with coding tasks in a terminal environment."""

    def __init__(self, name):
        self.name = name
        self.messages = []
        self.agent: Agent | None = None
        self.tools: list[Tool] = [
            read_file,
            run_command,
            grep_files,
            list_files,
            write_file,
            get_current_dir
        ]
        self.model_config = ModelConfig()

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the current model."""
        selected_key = self.model_config.get_selected_model()
        models = self.model_config.get_available_models()
        model_info = models.get(selected_key, {})

        return {
            "key": selected_key,
            "name": model_info.get("model_name", selected_key),
            "description": model_info.get("description", "Unknown model"),
            "type": model_info.get("type", "unknown"),
            "base_url": model_info.get("base_url", ""),
            "env_key": model_info.get("env_key", ""),
            "status": self._check_model_status(model_info)
        }

    def _check_model_status(self, model_info: Dict[str, Any]) -> str:
        """Check if the model is available and configured."""
        env_key = model_info.get("env_key", "")

        if model_info.get("type") == "local":
            # For local models, we just check if the base URL is accessible
            return "available" if model_info.get("base_url") else "unavailable"

        if env_key:
            api_key = os.getenv(env_key)
            if api_key:
                return "configured"
            else:
                return "missing_api_key"

        return "unknown"

    def list_available_models(self) -> Dict[str, Dict[str, Any]]:
        """List all available models with their status."""
        models = self.model_config.get_available_models()
        result = {}

        for key, config in models.items():
            status = self._check_model_status(config)
            result[key] = {
                "name": config.get("model_name", key),
                "description": config.get("description", ""),
                "type": config.get("type", "unknown"),
                "status": status,
                "is_selected": key == self.model_config.get_selected_model()
            }

        return result

    def switch_model(self, model_key: str):
        """Switch to a different model."""
        models = self.model_config.get_available_models()
        if model_key not in models:
            raise ValueError(
                f"Model '{model_key}' not found. Available models: {list(models.keys())}")

        self.model_config.set_selected_model(model_key)
        # Reset the agent to use the new model
        self.agent = None

    @traceable(name="Change Mode")
    def setup(self):
        """Setup the agent with the selected model."""
        selected_key = self.model_config.get_selected_model()
        models = self.model_config.get_available_models()
        model_config = models.get(selected_key, {})

        if not model_config:
            raise ValueError(
                f"Model configuration for '{selected_key}' not found")

        model_type = model_config.get("type")
        model_name = model_config.get("model_name", selected_key)
        base_url = model_config.get("base_url")
        env_key = model_config.get("env_key", "")

        if model_type == "api":
            api_key = os.getenv(env_key)
            if not api_key:
                raise ValueError(
                    f"API key for {selected_key} not found. "
                    f"Please set {env_key} in your .env file."
                )

            client = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
            )
            model = OpenAIChatCompletionsModel(
                model=model_name,
                openai_client=client,
            )

        elif model_type == "local":
            client = AsyncOpenAI(
                base_url=base_url,
                api_key="",  # No API key needed for local Ollama
            )
            model = OpenAIChatCompletionsModel(
                model=model_name,
                openai_client=client,
            )

        else:
            raise ValueError(f"Unknown model type: {model_type}")

        self.agent = Agent(
            name=self.name,
            instructions="""
You are a coding assistant running inside a tmux pane.
The user will send you code snippets or questions from their editor.
You have tools to read files, run commands, and search code.
Use them proactively — don't just answer from the snippet alone.
Read surrounding context, check imports, run tests, check git history
if it helps you give a better answer.

Be concise. Code first, explanation after.
If asked to modify code, show the diff or write the file directly.
""",
            tools=self.tools,
            model=model,
        )

    def add_message(self, role: str, content: str):
        """Add a message to the conversation history."""
        self.messages.append({"role": role, "content": content})

    def clear_messages(self):
        """Clear the conversation history."""
        self.messages = []

    def get_message_count(self) -> int:
        """Get the number of messages in the conversation history."""
        return len(self.messages)//2  # Each turn has a user and assistant message

    @traceable(run_type='llm', name="Stream Response")
    async def stream_response(self, user_input: str):
        """Get a response from the agent based on user input."""
        if not self.agent:
            self.setup()

        self.add_message("user", user_input)

        response = Runner.run_streamed(
            self.agent,
            self.messages,
            max_turns=50
        )

        thinking_response = ""
        text_response = ""
        async for event in response.stream_events():
            if isinstance(event, RawResponsesStreamEvent):
                if isinstance(event.data, ResponseReasoningTextDeltaEvent):
                    delta = event.data.delta or ""
                    thinking_response += delta
                    yield ('thinking', delta)
                elif isinstance(event.data, ResponseTextDeltaEvent):
                    delta = event.data.delta or ""
                    text_response += delta
                    yield ('text', delta)
            elif isinstance(event, RunItemStreamEvent):
                if event.name == "tool_called":
                    tool_name = event.item.raw_item.name
                    yield ('tool_call', tool_name)
                elif event.name == "tool_output":
                    yield ('tool_response', event.item.output)

        if thinking_response:
            self.messages.append({
                'id': '__fake_id__',
                'type': 'reasoning',
                'summary': [{'text': thinking_response, 'type': 'summary_text'}]
                })

        self.add_message("assistant", text_response)


# agent = TmuxAgent(name="tmux-agent")
_agent = None  # Initialize the agent lazily to avoid setup issues on import

def get_agent() -> TmuxAgent:
    """Get the singleton instance of TmuxAgent."""
    global _agent
    if _agent is None:
        _agent = TmuxAgent(name="tmux-agent")
    return _agent
