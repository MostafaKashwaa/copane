# Changelog

All notable changes to Copane will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
with PEP 440 pre-release tags.

## [0.1.0a1] — Unreleased

### Added

- **Turn-boundary summarization** — tool outputs are compressed to metadata
  stubs in-place between conversation turns (e.g. `read_file` results become
  `path (N lines, first def/docstring hint)`). Deterministic — no LLM call,
  no cost, <10ms. Conversation shape (message count/order) is fully preserved.
- **Full conversation history saving** — before each summarization, the
  complete message list is written to
  `~/.copane/logs/session_<timestamp>.json`.
- **SDK-native tool approval** — `write_file` approval now uses the OpenAI
  Agents SDK's built-in `ToolApprovalItem`/`RunState.approve()` mechanism
  instead of a custom confirmation session. Diff preview displayed before
  the y/n/a/r/q prompt.
- **Conversation history module** (`conversation_history.py`) — extracted from
  `tmux_agent.py`. Manages message storage, memory safety, and trimming with
  four independent safety nets: 100-message cap, 75-message trim target,
  5 MB byte budget, and 8,000-char reasoning truncation. Includes orphan
  repair after trimming (removes `function_call_output` messages whose
  matching `function_call` was dropped).
- **Model config module** (`model_config.py`) — CRUD operations for
  `~/.config/tmux-agent/model_config.json` with auto-generated defaults for
  DeepSeek, OpenAI, and local Ollama.
- **Model provider module** (`model_provider.py`) — extracted from
  `tmux_agent.py`. Handles model discovery, liveness checks, Agent
  construction, and system prompt assembly.
- **Chain-of-thought display** — reasoning/thinking tokens from DeepSeek and
  other CoT models are shown in the streaming UI, distinguished from normal
  output.
- **Tool output enrichment** — `ToolResult` now carries structured metadata:
  `output` (string), `error_type` (str | None), and `truncated` (bool).
  Callers can inspect the result programmatically instead of parsing strings.
- **Tool schema validation** — `_strip_config_from_schema()` removes non-typed
  config parameters from tool schemas before sending to the OpenAI API,
  preventing invalid schema errors.
- **Dangerous command heuristics** — `run_command` blocks known destructive
  patterns (e.g. `rm -rf /`, `git push --force`, recursive chmod/chown).
- **Byte-level truncation** — `_truncate()` helper limits `run_command` and
  `grep_files` output by byte count, not just line count.
- **Diff preview module** (`preview.py`) — extracted from `ui.py` for cleaner
  separation of concerns.
- **Version discovery** (`_version.py`) — reads version from `pyproject.toml`
  as the single source of truth, with `importlib.metadata` fallback for
  installed packages. Used by CLI banner and UI status panel.
- **GitHub Actions CI** — test workflow runs pytest on PRs to `dev`.
- **Project reference files:**
  - `COPANE.md` — operational reference for coding agents with tools (repo
    tree, architecture, known issues, development commands).
  - `PROJECT.md` — comprehensive overview for pure LLMs (what, why, how,
    who, marketing angles, Q&A).
- **Tests:** `test_conversation_history.py` (572 lines),
  `test_model_config.py` (142 lines), `test_model_provider.py` (489 lines),
  `test_tmux_agent.py` (1,250 lines), `test_tool_approval.py` (122 lines),
  plus dedicated test files for all six tools (`test_tool_read_file.py`,
  `test_tool_run_command.py`, `test_tool_grep_files.py`,
  `test_tool_list_files.py`, `test_tool_write_file.py`,
  `test_tool_get_current_dir.py`), `test_tool_result.py`, and
  `test_tool_schema.py`. 89+ tool tests passing.

### Changed

- **`tmux_agent.py` refactored** — three modules extracted
  (`conversation_history.py`, `model_config.py`, `model_provider.py`),
  totaling 610 lines split from what was a 322-line monolithic file. Event
  handling moved from `stream_response()` into focused helper methods:
  `_handle_tool_call()`, `_handle_tool_output()`, `_handle_approval()`,
  `_handle_chunk()`. SDK-native message shapes throughout.
- **Tools restructured** — monolithic `tools.py` (464 lines) split into a
  `tools/` package with one module per tool:
  - `tools/__init__.py` — `TOOL_SUMMARIZERS` registry, `create_tools()` factory
  - `tools/_base.py` — shared `ToolResult`, `_truncate()`, `_get_truncated()`
  - `tools/read_file.py`, `tools/run_command.py`, `tools/grep_files.py`,
    `tools/list_files.py`, `tools/write_file.py`, `tools/get_current_dir.py`
  Each tool exports its own `summarize()` function.
- **Summarization strategy changed** — from destructive removal (deleting
  whole turns) to in-place metadata stubs on the `output` field of
  `function_call_output` messages. Messages stored in SDK-native shapes
  (dicts matching `ChatCompletionMessageParam`). Tool calls bridged to
  outputs via a `call_id`-keyed dict per turn.
- **CLI and UI extracted** from `app.py` — `cli.py` for argument parsing,
  `ui.py` for rendering. Terminal styling moved to `term_styles.py`.
  Professional 256-color ANSI terminal UI.
- **Tests organized** — `conftest.py` with shared fixtures, one test file per
  module under test.
- **Version set to `0.1.0a1`** — single source of truth in `pyproject.toml`,
  consumed by `_version.py`, used by `cli.py` and `ui.py`.

### Fixed

- **Terminal corruption** — `write_file` invoked during agent streaming no
  longer corrupts the terminal display.
- **OpenAI invalid schema errors** — `_strip_config_from_schema()` removes
  non-typed config params from tool schemas before API submission.
- **Orphaned tool outputs** — after history trimming,
  `function_call_output` messages without a matching `function_call` are
  now repaired (removed) to keep the conversation valid for the SDK.
- **Empty file reading** — `read_file` no longer fails on empty files.
- **User path expansion** — `~` paths handled correctly in all tools.
- **UI consistency** — approval flow and status display edge cases resolved.
- **Version inconsistency** — `cli.py` and `ui.py` no longer hardcode
  `"1.0.0"`; both read from `_version.py` → `pyproject.toml`.

### Known issues

- `pydantic`, `python-dotenv`, and `httpx` are used directly but appear only
  as transitive dependencies of `openai-agents` (not declared in
  `pyproject.toml`).
- `autopep8` is declared in `pyproject.toml` but never imported.
- System prompt in `model_provider.py` has two typos ("wheather", "ouput").
- No integration tests for agent-level behavior (streaming, summarization,
  tool approval loop) — only unit tests for individual modules and tools.
- CI runs only on PRs to `dev`; no scheduled runs or test matrix across
  Python versions yet.
