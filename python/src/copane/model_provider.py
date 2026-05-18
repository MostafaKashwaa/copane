"""Model provider for copane — model discovery, status checks, and Agent creation.

Provides ``ModelProvider`` — the single source of truth for which models
are available, whether they are reachable, and how to build an
``Agent`` for the currently-selected one.
"""

import logging
import os
from typing import Any, Dict

from agents import Agent, OpenAIChatCompletionsModel, Tool
from openai import AsyncOpenAI

from copane.tracing import traceable

from copane.model_config import ModelConfig

logger = logging.getLogger(__name__)


class ModelProvider:
    """Knows about models and can create Agent instances from them.

    Owns the ``ModelConfig`` instance and all the logic for checking
    model reachability, listing available models, switching the
    selected model, and building an ``Agent`` for the current selection.

    Does **not** own the runtime ``agent`` reference — that belongs to
    ``TmuxAgent``, which calls ``create_agent`` and stores the result.
    """

    def __init__(self, model_config: ModelConfig | None = None):
        self.model_config = model_config or ModelConfig()

    # ── Model info & listing ────────────────────────────────────────

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the currently selected model."""
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
            "status": self.check_model_status(model_info),
        }

    @staticmethod
    def check_model_status(model_info: Dict[str, Any]) -> str:
        """Check the availability status of a model.

        Returns one of:

        * ``"available"`` — local model responding on its base URL
        * ``"configured"`` — API model with its key set
        * ``"missing_api_key"`` — API model whose env var is empty
        * ``"unreachable"`` — local model not responding
        * ``"unavailable (local model missing base_url)"`` — local with no URL
        * ``"Cannot check (httpx not installed)"`` — local, no httpx
        * ``"unknown"`` — no type or env_key to check
        """
        env_key = model_info.get("env_key", "")

        if model_info.get("type") == "local":
            ollama_url = model_info.get("base_url")
            if ollama_url:
                try:
                    import httpx

                    response = httpx.get(ollama_url + "/models", timeout=2)
                    if response.status_code == 200:
                        return "available"
                    else:
                        return "unreachable (try running 'ollama serve' or correcting base_url)"
                except ImportError:
                    return "Cannot check (httpx not installed)"
                except Exception:
                    return "unreachable"
            else:
                return "unavailable (local model missing base_url)"

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
            status = self.check_model_status(config)
            result[key] = {
                "name": config.get("model_name", key),
                "description": config.get("description", ""),
                "type": config.get("type", "unknown"),
                "status": status,
                "is_selected": key == self.model_config.get_selected_model(),
            }

        return result

    # ── Model switching ─────────────────────────────────────────────

    def switch_model(self, model_key: str):
        """Switch the selected model in the backing config.

        Raises ``ValueError`` if *model_key* is not in available_models.
        """
        models = self.model_config.get_available_models()
        if model_key not in models:
            raise ValueError(
                f"Model '{model_key}' not found. Available models: {list(models.keys())}"
            )

        self.model_config.set_selected_model(model_key)

    # ── Agent creation ──────────────────────────────────────────────

    @traceable(name="Create Agent")
    def create_agent(
        self,
        tools: list[Tool],
        agent_name: str,
    ) -> Agent:
        """Build and return an ``Agent`` for the currently selected model.

        The caller is responsible for storing the returned Agent.
        """
        selected_key = self.model_config.get_selected_model()
        models = self.model_config.get_available_models()
        model_config = models.get(selected_key, {})

        if not model_config:
            raise ValueError(
                f"Model configuration for '{selected_key}' not found"
            )

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
                api_key="",
            )
            model = OpenAIChatCompletionsModel(
                model=model_name,
                openai_client=client,
            )

        else:
            raise ValueError(f"Unknown model type: {model_type}")

        return Agent(
            name=agent_name,
            instructions="""
You are a coding assistant running inside a tmux pane.
The user will send you code snippets or questions from their editor.
You have tools to read files, run commands, and search code.
Tool outputs are JSON objects with a `success` boolean, an output string, an error_type string or null, 
and a `truncated` boolean indicates wheather the ouput is truncated.
Use the tools proactively — don't just answer from the snippet alone.
Before calling a tool, briefly say what you're about to do and why, in one natural sentence.
Read surrounding context, check imports, run tests, check git history
if it helps you give a better answer.

Be concise. Code first, explanation after.
If asked to modify code, show the diff or write the file directly.
If the you tried a tool that makes changes and needs approval, and the changes were not approved, do not retry, instead
ask the user about the reason for the rejection and how to proceed.

## Conversation memory

Between turns, tool outputs are compressed to metadata stubs in-place
(path, line count, purpose hint for file reads; exit code + preview
for commands; etc.). Exact file contents are NOT retained across turns.
The conversation shape is preserved — you see every tool call and its
summarized result in the original order.

- Gather all needed information from files within the current turn.
- At the start of a new turn, re-read key files if exact content is
  needed (one read_file call per file gets full contents).
- Use grep_files first to locate relevant sections, then read_file
  with start_line/end_line to zoom in.
""",
            tools=tools,
            model=model,
        )
