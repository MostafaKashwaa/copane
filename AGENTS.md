# copane — Project Reference for AI Agents

> Read this file before making changes. It reflects the **current** state of
> the codebase and is designed to give any model the context needed to work
> productively without re-exploring from scratch.

## What is copane?

An AI coding assistant that runs **inside a tmux pane** and integrates with
**Vim/Neovim**. The user chats with an LLM (DeepSeek, GPT-4o, Ollama, or
any OpenAI-compatible endpoint) which has tools to read files, run commands,
search code, list directories, and write files — all within the user's real
project directory.

Key principle: the agent operates on real files. No sandbox, no virtual
workspace.

## Repository layout

The repo root is a **Vim/Neovim plugin**. The `python/` subdirectory is a
standalone Python package that contains the agent.

```
copane/                              # Git repo root (= Vim plugin root)
├── plugin/copane.vim                # Vim plugin entry point — commands, mappings, autocmds
├── autoload/
│   ├── copane.vim                   # Config-file editing helpers (edit model config, secrets)
│   └── tmux_agent.vim               # Core tmux pane lifecycle (open, close, send, focus, toggle)
├── ftplugin/
│   ├── python.vim                   # Python-specific mappings (explain, test, refactor)
│   └── javascript.vim               # JS/TS-specific mappings
├── after/ftplugin/
│   └── python.vim                   # Compatibility shims for python-mode, jedi, ALE, coc, etc.
├── doc/copane.txt                   # Vim help file (:help copane)
│
├── python/                          # *** Python package root ***
│   ├── pyproject.toml               # Package metadata, dependencies, pytest config
│   ├── uv.lock                      # Lockfile for uv (reproducible installs)
│   ├── setup_python.sh              # Venv bootstrap script (called by Vim plugin or manually)
│   ├── src/copane/                  # *** Source code ***
│   │   ├── __init__.py              # Empty — no top-level re-exports
│   │   ├── _version.py              # Version discovery (reads pyproject.toml)
│   │   ├── app.py                   # Entry point: async REPL, prompt_toolkit, special commands
│   │   ├── cli.py                   # CLI argument parsing, --mode dispatch, model display
│   │   ├── tmux_agent.py            # TmuxAgent: orchestrator, streaming, tool approval, summarization
│   │   ├── conversation_history.py  # ConversationHistory: message storage, memory safety, trimming
│   │   ├── model_config.py          # ModelConfig: CRUD for ~/.config/tmux-agent/model_config.json
│   │   ├── model_provider.py        # ModelProvider: model discovery, status checks, Agent creation
│   │   ├── ui.py                    # Streaming display, banner, approval prompts
│   │   ├── preview.py               # Diff preview formatting for tool approval
│   │   ├── file_utils.py            # @filename completion (FileCompleter) and expansion
│   │   ├── completers.py            # Multi-mode completer (files, slash commands, model keys)
│   │   ├── term_styles.py           # ANSI colors, logos, prompt_toolkit styles, print helpers
│   │   ├── renderers/               # Pluggable streaming response renderers
│   │   │   ├── __init__.py          # get_renderer() factory, AVAILABLE_RENDERERS registry
│   │   │   ├── _base.py             # Renderer ABC — lifecycle + chunk handlers
│   │   │   ├── raw_renderer.py      # RawRenderer — passthrough (default)
│   │   │   ├── regex_renderer.py    # RegexRenderer — inline **bold**, *italic*, `code`
│   │   │   ├── markdown_it_renderer.py  # MarkdownItRenderer — streaming markdown-it-py
│   │   │   └── rich_buffer_renderer.py  # RichBufferRenderer — raw-then-replace with rich
│   │   ├── tools/                   # Tool implementations
│   │   │   ├── __init__.py          # Re-exports all tools + TOOL_SUMMARIZERS registry
│   │   │   ├── _base.py             # Shared: ToolResult, truncation, danger heuristics, schema helpers
│   │   │   ├── read_file.py         # read_file tool + summarize()
│   │   │   ├── run_command.py       # run_command tool + summarize()
│   │   │   ├── grep_files.py        # grep_files tool + summarize()
│   │   │   ├── list_files.py        # list_files tool + summarize()
│   │   │   ├── write_file.py        # write_file tool + summarize() (needs_approval=True)
│   │   │   └── get_current_dir.py   # get_current_dir tool + summarize()
│   │   ├── check_deps.py            # DEAD CODE — not imported by anything
│   │   ├── display.py               # DEAD CODE — unused format_output function
│   │   └── display_strategies.py    # DEAD CODE — prototype display strategies, never imported
│   └── tests/                       # pytest test suite
│       ├── conftest.py              # Fixtures (tmp_dir, sample_file) and helpers (invoke, parse_result)
│       ├── test_tool_read_file.py
│       ├── test_tool_run_command.py
│       ├── test_tool_grep_files.py
│       ├── test_tool_list_files.py
│       ├── test_tool_write_file.py
│       ├── test_tool_get_current_dir.py
│       ├── test_tool_helpers.py
│       ├── test_tool_schema.py
│       ├── test_tool_result.py
│       ├── test_tool_approval.py
│       ├── test_tmux_agent.py
│       ├── test_model_provider.py
│       ├── test_model_config.py
│       └── test_conversation_history.py
│
├── rplugin/python3/tmux_agent.py    # DEAD CODE — legacy Neovim RPC plugin, broken imports
├── install.sh                       # Standalone terminal installer (clones repo, creates venv)
├── setup_python.sh                  # Symlink/copy of python/setup_python.sh
├── uninstall.sh                     # Cleanup script
├── config.example.json              # Extended model config example (more models than defaults)
├── .env.example                     # Environment template
├── .github/workflows/test.yml       # CI — runs pytest on PRs to main/dev
├── README.md                        # User-facing documentation
├── AGENTS.md                        # This file — project reference for AI agents
└── COPANE.md                        # Older project reference (kept for historical context)
```

> **Note:** The `guides/` directories (both `python/guides/` and the root
> `guides/`) contain working notes, design documents, and implementation
> plans. They are gitignored (not shipped) but are referenced during
> development; some may be outdated.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Vim/Neovim                                                      │
│  ┌──────────────┐   :CopaneSend    ┌─────────────────────────┐   │
│  │ plugin/      │   ──────────────→│ autoload/tmux_agent.vim │   │
│  │ copane.vim   │                  │ (tmux pane management)  │   │
│  └──────────────┘                  └───────────┬─────────────┘   │
│                                                │                 │
│  User presses <leader>ts                       │ tmux send-keys  │
│  → visual selection sent                       │ + focus         │
└────────────────────────────────────────────────┼─────────────────┘
                                                 │
                    ┌────────────────────────────▼──────────────────┐
                    │  tmux pane running copane                     │
                    │                                               │
                    │  python3 -m copane.app                        │
                    │  ┌──────────────────────────────────────┐     │
                    │  │ Async REPL (prompt_toolkit)          │     │
                    │  │  • Multi-mode completion (Tab)       │     │
                    │  │    - @filename → FileCompleter       │     │
                    │  │    - /command → CommandCompleter      │     │
                    │  │    - /switch <key> → ModelKeyCompleter│     │
                    │  │  • Multiline input (Ctrl+J to submit) │     │
                    │  │  • Special commands (/switch, /clear) │     │
                    │  └──────────────┬───────────────────────┘     │
                    │                 │ user_input                  │
                    │  ┌──────────────▼───────────────────────┐     │
                    │  │ TmuxAgent.stream_response()          │     │
                    │  │  • Runner.run_streamed()             │     │
                    │  │  • Tool approval loop                │     │
                    │  │  • Reasoning truncation              │     │
                    │  │  • Turn-boundary summarization       │     │
                    │  │  • Message trimming (safety net)     │     │
                    │  └──────────────┬───────────────────────┘     │
                    │                 │ (kind, chunk) tuples        │
                    │  ┌──────────────▼───────────────────────┐     │
                    │  │ ui.py → print_streamed_response()    │     │
                    │  │  • Dispatches to active Renderer      │     │
                    │  │    for thinking + text chunks         │     │
                    │  │  • Handles tool_call, tool_response,  │     │
                    │  │    tool_approval directly (no renderer)│     │
                    │  └──────────────┬───────────────────────┘     │
                    │                 │                             │
                    │  ┌──────────────▼─────────────────────────┐   │
                    │  │ renderers/ package (4 renderers)       │   │
                    │  │  • RawRenderer — passthrough (default) │   │
                    │  │  • RegexRenderer — inline ANSI markup  │   │
                    │  │  • MarkdownItRenderer — streaming parse│   │
                    │  │  • RichBufferRenderer — raw then rich  │   │
                    │  └────────────────────────────────────────┘   │
                    │                 │ tool calls                  │
                    │  ┌──────────────▼─────────────────────────┐   │
                    │  │ tools/ package (6 tools)               │   │
                    │  │  • read_file, run_command, grep_files  │   │
                    │  │  • list_files, get_current_dir         │   │
                    │  │  • write_file (needs_approval=True)    │   │
                    │  │  • Blocked commands (danger heuristics)│   │
                    │  │  • Each tool exports summarize() for   │   │
                    │  │    turn-boundary compression           │   │
                    │  └────────────────────────────────────────┘   │
                    └───────────────────────────────────────────────┘
```

### Data flow for a user query

1. User types in the REPL (or sends from Vim via tmux send-keys)
2. `@filename` tokens are expanded to file contents by `expand_files()` in `file_utils.py`
3. `TmuxAgent.stream_response()` is an async generator that yields `(kind, chunk)` tuples
4. `kind` is one of: `"thinking"`, `"text"`, `"tool_call"`, `"tool_response"`, `"tool_approval"`
5. `ui.py` dispatches `"thinking"` and `"text"` chunks to the active `Renderer`
6. Tool calls, tool responses, and approval prompts are handled directly by `ui.py` (they do not vary between renderers)
7. For tool approval, `ui.py` shows a preview (diff for write_file, command for run_command) via `preview.py`
8. After the response completes, the assistant message is stored in `ConversationHistory`
9. On the *next* user message, `_summarize_previous_turn()` compresses tool outputs in-place

### Startup flow

1. Vim sources `plugin/copane.vim` → defines commands, autocmds, mappings
2. On `VimEnter`, `s:setup()` runs (deferred 100ms) → checks prerequisites, sets up venv path
3. User runs `:CopaneOpen` → calls `tmux_agent#open()`
4. `tmux_agent#open()` checks/creates venv via `setup_python.sh`, then creates a tmux split-pane running `python3 -m copane.app --env-file ~/.copane.env`
5. `app.py` loads env file → creates `TmuxAgent` singleton → selects renderer via `get_renderer()` → prints banner → enters REPL loop

## Key files — what to touch for common tasks

| File | Touch when you need to... |
|------|---------------------------|
| `python/src/copane/tmux_agent.py` | Change streaming, tool approval flow, agent setup, system prompt, summarization dispatch |
| `python/src/copane/conversation_history.py` | Change message storage, memory limits, trimming logic, byte budget, reasoning truncation |
| `python/src/copane/tools/` | Add/modify tools, change truncation limits, add danger patterns |
| `python/src/copane/tools/_base.py` | Change `ToolResult` model, shared truncation, danger heuristics |
| `python/src/copane/tools/__init__.py` | Register a new tool (imports + `TOOL_SUMMARIZERS` dict) |
| `python/src/copane/app.py` | Change REPL behavior, add slash commands, modify startup, renderer selection |
| `python/src/copane/cli.py` | Change CLI args, `--mode` dispatch, model info display |
| `python/src/copane/ui.py` | Change streaming display, banner, approval prompt UI, renderer dispatch |
| `python/src/copane/renderers/` | Add/modify renderers: streaming output formatting for thinking + text chunks |
| `python/src/copane/renderers/_base.py` | Change `Renderer` ABC — lifecycle and chunk-handler contract |
| `python/src/copane/renderers/__init__.py` | Register a new renderer (add to `get_renderer()` + `AVAILABLE_RENDERERS`) |
| `python/src/copane/completers.py` | Change Tab-completion: file paths, slash commands, model keys |
| `python/src/copane/preview.py` | Change diff/preview formatting for tool approval |
| `python/src/copane/model_config.py` | Change model config CRUD, default models |
| `python/src/copane/model_provider.py` | Change model status checks, Agent construction, system prompt |
| `python/src/copane/file_utils.py` | Change @filename completion or expansion |
| `python/src/copane/term_styles.py` | Change colors, logos, prompt_toolkit styles, print helpers |
| `autoload/tmux_agent.vim` | Change tmux pane lifecycle, Python venv setup |
| `plugin/copane.vim` | Change Vim commands, mappings, autocmds |

## How renderers work

### Renderer contract

Every renderer inherits from `Renderer` (ABC in `renderers/_base.py`) and implements
four methods:

```python
class Renderer(ABC):
    def on_response_begin(self) -> None: ...
    def on_response_complete(self) -> None: ...
    def on_thinking_chunk(self, chunk: str) -> None: ...
    def on_text_chunk(self, chunk: str) -> None: ...
```

- **`on_response_begin()`** — called once before the first chunk. Use for headers,
  state initialization.
- **`on_thinking_chunk(chunk)`** — receives each raw thinking/reasoning chunk.
- **`on_text_chunk(chunk)`** — receives each markdown-formatted response text chunk.
- **`on_response_complete()`** — called once after the final chunk. Use for cleanup,
  flushing buffers, or replacing raw output with formatted output.

**Key principle:** Renderers only handle `"thinking"` and `"text"` chunks.
Tool calls, tool responses, and tool approval are handled directly in
`ui.py` — they do NOT vary between renderers.

### Available renderers

| Name | Class | Description | Dependencies |
|------|-------|-------------|--------------|
| `raw` | `RawRenderer` | Passthrough — prints chunks as-is (default, pre-renderer behaviour) | None |
| `regex` | `RegexRenderer` | Converts `**bold**`, `*italic*`, `` `code` ``, and `### headings` to ANSI on-the-fly | None |
| `markdown_it` | `MarkdownItRenderer` | Streaming CommonMark parser; buffers chunks, renders stable blocks to ANSI | `markdown-it-py` |
| `rich_buffer` | `RichBufferRenderer` | Prints raw during streaming, clears and replaces with `rich.Markdown` on completion | `rich` |

### Renderer selection

Controlled by the `COPANE_RENDERER` environment variable. Set it in `~/.copane.env`:

```bash
COPANE_RENDERER=regex
```

Or at runtime in any shell before starting copane. Default is `"raw"`.

The factory function `get_renderer(name=None)` in `renderers/__init__.py` reads
the env var and returns the appropriate `Renderer` instance. Unknown names
raise `ValueError`; missing optional dependencies raise `ImportError`.

### Adding a new renderer

1. Create `renderers/my_renderer.py` with a class inheriting from `Renderer`
2. Implement all four abstract methods
3. In `renderers/__init__.py`:
   - Import the class (lazily if it has optional deps)
   - Add a `case "my_renderer"` branch in `get_renderer()`
   - Add an entry to `AVAILABLE_RENDERERS`
4. If the renderer needs a new optional dependency, add it to
   `[project.optional-dependencies]` in `pyproject.toml`

## How completers work

The `CopaneCompleter` in `completers.py` is a multi-mode Tab completer for
the REPL. It inspects the input context and delegates:

| Context | Completer | Example |
|---------|-----------|---------|
| `@partial_path` | `FileCompleter` (from `file_utils.py`) | `@src/main` → `@src/main.py` |
| `/partial_cmd` (no space) | `CommandCompleter` | `/sw` → `/switch` |
| `/switch partial_key` | `ModelKeyCompleter` | `/switch dee` → `deepseek-chat` |

`CommandCompleter` offers: `/switch`, `/clear`, `/models`, `/modelinfo`, `/help`.

`ModelKeyCompleter` reads available keys from `ModelConfig` on each activation
(so it stays in sync if the user edits the config file).

## How tools work

### Tool file structure

Every tool file in `tools/` exports exactly two things:

1. **`tool`** — the `@function_tool` + `@traceable(run_type="tool")` decorated function
2. **`summarize(args: dict, output: str) -> str | None`** — deterministic summarizer

Adding a new tool:
1. Create `tools/my_tool.py` with `tool` and `summarize`
2. Import both in `tools/__init__.py`, add to `TOOL_SUMMARIZERS` dict
3. Add `tool` to the `self.tools` list in `TmuxAgent.__init__()` (`tmux_agent.py`)
4. Call `_strip_config_from_schema(my_tool.params_json_schema)` at module level in the tool file

### Decorator order matters

```python
@function_tool          # ← bottom (builds JSON schema from the function signature)
@traceable(run_type="tool")  # ← top (wraps function, injects `config` param)
def my_tool(...) -> ToolResult:
```

`@traceable` adds a `config` keyword parameter. `@function_tool` then picks up
that extra param in its schema. `_strip_config_from_schema()` removes it so
OpenAI's API doesn't reject the schema (it requires every property to have a `type`).

### ToolResult

All tools return `ToolResult` (a Pydantic BaseModel):

```python
class ToolResult(BaseModel):
    success: bool
    output: str = ""
    error: str = ""
    error_type: str = ""    # e.g. "file_not_found", "blocked_command", "timeout"
    truncated: bool = False
```

The system prompt tells the LLM about this structure. **Changing `ToolResult`
requires updating the system prompt in `model_provider.py` too.**

### Truncation limits

| Tool | Limit | Constant |
|------|-------|----------|
| `run_command` | 8,000 chars | `_MAX_OUTPUT` in `_base.py` |
| `grep_files` | 5,000 chars | `_MAX_GREP_OUTPUT` in `_base.py` |
| `read_file` | 50,000 chars | `_MAX_READ_FILE_SAFETY_LIMIT` in `_base.py` |
| `list_files` | 200 entries | Via `head -200` in shell command |

### Tool approval

Only `write_file` has `needs_approval=True`. The approval flow:

1. `Runner.run_streamed()` returns a stream with `response.interruptions`
2. `stream_response()` yields `("tool_approval", (item, state))` to the UI
3. UI shows a preview (diff for files, command for shell) via `preview.py`
4. User responds: `y` (approve), `n` (reject), `a` (always approve), `r` (always reject), `q` (quit)
5. `handle_tool_approval()` calls `state.approve()` or `state.reject()`
6. `_recreate_runner()` releases old response, forces `gc.collect()`, re-enters `run_streamed()`

### Danger heuristics

`run_command` blocks commands matching these patterns (in `_base.py`):
- `rm -rf /` or `~/`
- `dd if=`
- `> /dev/...`
- `mkfs.*`
- Fork bombs `:(){ ...`
- `chmod -R 0000`
- `mv / /dev/null`

## Conversation memory management

### Turn-boundary summarization (primary strategy)

When the user sends a new message, all tool outputs from the previous turn
are compressed to metadata stubs **in-place**:

- `read_file` → `- path (N lines): <purpose hint from docstring/first def>`
- `run_command` → `- cmd → exit N: <first 200 chars of output>`
- `grep_files` → `- grep "pattern" → matches in file1, file2 (N matches)`
- `list_files` → `- path (depth N): N entries`
- `write_file` → `- path: Wrote N chars to path`
- `get_current_dir` → no summary (returns `None`)

The dispatch happens in `TmuxAgent._summarize_previous_turn()` via the
`TOOL_SUMMARIZERS` dict. The conversation shape (message count, order) is
preserved — only the `output` field of function_call_output messages changes.

**Implication for the LLM:** File contents do NOT persist across turns.
The model must re-read files each turn to get current content.

### Safety nets (belt-and-suspenders)

| Mechanism | Limit | Location |
|-----------|-------|----------|
| Message count cap | 100 messages | `conversation_history.py` `MAX_MESSAGES` |
| Trim target | 75 messages (75% of cap) | `TRIM_TARGET_FRACTION` |
| Byte budget | 5 MB total | `MAX_HISTORY_BYTES` |
| Byte-budget trim | Keep 20 most recent | `KEEP_RECENT_MESSAGES` |
| Reasoning truncation | 8,000 chars per reasoning block | `MAX_REASONING_CHARS` |
| read_file safety | 50,000 chars per read | `_MAX_READ_FILE_SAFETY_LIMIT` |

### Full history persistence

Before each summarization, the complete message list is saved to
`~/.copane/logs/session_<timestamp>.json`. This is done by
`TmuxAgent._save_full_history()`.

### Orphan repair

After any trimming, `_repair_orphaned_outputs()` removes
`function_call_output` messages whose matching `function_call` was dropped.
The OpenAI Agents SDK requires every output to have a preceding call with
the same `call_id`.

## Configuration files

| File | Location | Purpose |
|------|----------|---------|
| Environment | `~/.copane.env` | API keys (`DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, etc.) + `COPANE_RENDERER` |
| Model config | `~/.config/tmux-agent/model_config.json` | Selected model, available models, endpoints |
| History | `~/.local/share/copane/.copane_history` | prompt_toolkit REPL history |
| Session logs | `~/.copane/logs/session_*.json` | Full message history dumps |

The model config is auto-generated on first run with defaults for DeepSeek,
OpenAI, and local Ollama. Users can add any OpenAI-compatible endpoint
(Groq, Anthropic via proxy, vLLM, etc.) by editing the config file.

## Dependencies

Declared in `python/pyproject.toml`:

| Package | Purpose |
|---------|---------|
| `openai-agents` | Agent SDK (`Agent`, `Runner`, `function_tool`, `ToolApprovalItem`) |
| `langsmith` | Tracing (`@traceable` decorator) |
| `prompt-toolkit` | Interactive REPL with completion and history |
| `pynvim` | Neovim remote plugin support (for `rplugin/`, currently broken) |
| `autopep8` | Declared but **never imported** — dead dependency |

Optional dependencies (`[renderers]` extras):

| Package | Purpose |
|---------|---------|
| `rich` | Rich terminal rendering (`RichBufferRenderer`) |
| `markdown-it-py` | Streaming CommonMark parser (`MarkdownItRenderer`) |

Used as transitive dependencies (should be declared explicitly):
- `pydantic` — `ToolResult` model
- `python-dotenv` — `load_dotenv()` in `app.py`
- `openai` — `AsyncOpenAI` client, response event types

Required system tools:
- `python3` (3.12+)
- `tmux`
- `grep` (used by `grep_files` tool)
- `find` (used by `list_files` tool)

## Running tests

```bash
cd python
.venv/bin/python -m pytest tests/ -v
```

CI runs `pytest -q --tb=short` in the `python/` directory on Python 3.12.

The test suite uses one test file per tool, plus tests for the agent,
model provider, model config, conversation history, and tool schema/fixtures.
`conftest.py` provides `tmp_dir`, `sample_file` fixtures and `invoke()` helper.

## In-repl commands

| Command | Action |
|---------|--------|
| `/models` | List available models |
| `/switch <key>` | Switch model |
| `/modelinfo` | Show current model info |
| `/clear` | Clear conversation history |
| `/help` | Show help |

Tab completion is available for slash commands and model keys.

## Vim commands and mappings

All mappings use `g:copane_mapping_prefix` (default `<leader>t`).

| Mapping | Action |
|---------|--------|
| `<leader>to` | Open/focus AI pane |
| `<leader>tc` | Close AI pane |
| `<leader>tt` | Toggle between editor and AI pane |
| `<leader>ts` | Send buffer (normal) or selection (visual) |
| `<leader>tm` | Show model info |
| `<leader>tM` | List models |
| `<leader>te` | Edit secrets file |
| `<leader>tE` | Edit model config |
| `<leader>th` | Help |

Filetype-specific (Python, JavaScript/TypeScript):
| Mapping | Action |
|---------|--------|
| `<leader>ta` | Send code |
| `<leader>te` | Explain code |
| `<leader>tt` | Write tests |
| `<leader>tr` | Refactor code |

## What NOT to change without careful thought

- **`ToolResult` schema** — the system prompt tells the LLM about it
- **`Renderer` ABC** — the four-method contract is the interface between `ui.py` and all renderers
- **`MAX_TOOL_TURNS=50`** in `tmux_agent.py` — hard cap on tool calls per round
- **The summarizer contract** `summarize(args, output) -> str | None` — every tool exports it
- **The singleton pattern** — `get_agent()` is called from both Vim and the REPL
- **Vim mappings** — user-facing and documented in README
- **Environment file path** (`~/.copane.env`) — hardcoded in multiple places
- **`_strip_config_from_schema` re-export** from `tools/__init__.py` — tests depend on it
- **The `for_api()` method** in `ConversationHistory` — strips internal fields before sending to the model API; the SDK requires clean dicts
- **The renderer dispatch in `ui.py`** — `"thinking"` and `"text"` go to the renderer; `"tool_call"`, `"tool_response"`, `"tool_approval"` are handled directly

## Known issues

1. **Version inconsistency:** `pyproject.toml` says `0.1.0a1`, `cli.py` and `ui.py` say `1.0.0`. `_version.py` reads from pyproject.toml but is unused.

2. **Dead code files:** `check_deps.py`, `display.py`, `display_strategies.py`, `rplugin/python3/tmux_agent.py` are not imported by anything live.

3. **Dead dependency:** `autopep8` is in `pyproject.toml` but never imported.

4. **Missing explicit dependencies:** `pydantic`, `python-dotenv`, and `httpx` are used directly but only available as transitive deps of `openai-agents`.

5. **System prompt typos:** "wheather" → "whether" and "ouput" → "output" in `model_provider.py`.

6. **Stale backup files:** `*.bak`, `*.swp` files in `src/copane/`.

7. **`list_files` has no `_truncate()` call** — output is limited only by `head -200` (entry count), not by byte length; unlike `run_command` and `grep_files` which apply `_truncate()`.

8. **`check_deps.py` references old path** `~/.vim/copane-venv` which no longer exists.

9. **`rplugin/python3/tmux_agent.py`** imports from nonexistent paths and will crash if Neovim loads it.

10. **No renderer tests** — the renderer package has no unit tests yet.

11. **`RichBufferRenderer` ANSI escape codes** — the cursor-up/clear sequence (`\\033[{N}F\\033[J`) assumes the raw output is still visible on screen; if the terminal scrolls, the replacement may misalign.

12. **`MarkdownItRenderer` stability boundary** — uses `\\n\\n` as the paragraph break heuristic; inline-only markdown (bold/italic/code without paragraph breaks) may not render until the response completes and `on_response_complete()` flushes the buffer.
