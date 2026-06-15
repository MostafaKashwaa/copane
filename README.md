# copane

A stateful AI coding agent that lives in your terminal and thinks in your editor.

**copane** is not a simple "chat widget." It is a full-turn, tool-using agent designed for complex, long-running engineering tasks. It reads your codebase, applies surgical edits, and maintains a coherent state across sessions—whether you are working directly in the CLI or from within Vim/Neovim.

## Choose Your Interface

- **Standalone CLI:** A powerful, agnostic shell for pure terminal speed. Work with the agent in any terminal environment.
- **Vim/Neovim Integration:** The "High-Context" interface. Launch the agent with your current buffer, visual selection, or project structure already in its immediate attention.

## Why Copane? (Operational Reliability)

Most AI agents struggle with cost, infinite loops, and "context drift." Copane is engineered to solve these operational hurdles:

- **Hallucination-Resistant Context:** Instead of feeding the model stale logs, Copane distills tool outputs into high-signal stubs. The agent sees your codebase as it exists **now**, preventing it from hallucinating based on outdated history.
- **Infinite Conversation Stability:** Built for the long haul. Includes automatic OOM (Out-of-Memory) protection and intelligent turn-truncation so you can keep a session open for days without a crash or token-limit failure.
- **Loop-Breaking Intelligence**: Applies a soft nudge before the turn limit, preventing the model from burning tokens in an unproductive cycle.
- **Token-Efficient Architecture:** Intelligent summarization of verbose command outputs ensures your API costs stay low while keeping the most relevant logic in the model's immediate attention span.

---

## Installation

### 1. Standalone Terminal (CLI)

Install the `copane` command to your terminal. This is the foundation of the tool.

```bash
curl -fsSL https://raw.githubusercontent.com/MostafaKashwaa/copane/main/install.sh | bash
```
*Prerequisites: `python3`, `python3-venv`, `git`.*

Make sure `~/.local/bin` is in your `PATH` (e.g., in your `~/.bashrc`). Then, set your API keys and launch:
```bash
copane
```

### 2. Vim/Neovim Plugin

The plugin allows you to pipe editor context directly into the agent. **Requires `tmux`.**

#### vim-plug
```vim
" In ~/.vimrc or ~/.config/nvim/init.vim
Plug 'MostafaKashwaa/copane'
```
#### lazy.nvim
```lua
{
  'MostafaKashwaa/copane',
  init = function()
    -- Optional: configure before load
    vim.g.copane_split_direction = 'horizontal'
  end,
}
```
#### Manual (Vim 8+ packages)
```bash
git clone https://github.com/MostafaKashwaa/copane.git \
  ~/.vim/pack/plugins/start/copane
```

---

## Usage & Interface

### Terminal CLI
The agent can be run interactively or for quick one-shot tasks.
```bash
# Interactive session
copane

# Quick action modes
copane --mode explain --file main.py
copane --mode test --text "def add(a,b): return a+b"

# Model management
copane --list-models
copane --switch gpt-4o
```

### Vim/Neovim Integration
Default prefix is `<leader>t`.

| Mapping | Mode | Action |
|---------|------|--------|
| `<leader>to` | normal | Open/focus the AI pane |
| `<leader>tc` | normal | Close the AI pane |
| `<leader>tw` | normal | Toggle between editor and AI pane |
| `<leader>ts` | normal/visual | Send buffer/selection to AI |
| `<leader>tm` | normal | Show current AI model info |
| `<leader>tv` | normal | Edit secrets (`~/.copane.env`) |
| `<leader>th` | normal | Show help |

**Commands:** `:CopaneOpen`, `:CopaneClose`, `:CopaneSend`, `:CopaneSwitchModel <key>`, `:CopaneClearHistory`.

### In the AI Pane (Slash Commands)
| Command | Action |
|---------|--------|
| `/models` | List available models |
| `/switch <name>` | Switch model |
| `/clear` | Clear conversation history |
| `/sessions` | List saved sessions |
| `/resume <id>` | Resume a saved session |
| `/renderer [key]` | List or switch response renderer |
| `/view <id>` | View the full conversation history of a session in a pager |
| `/save <name>` | Save the current conversation with a custom name |
Include files in your query with **`@filename`**. Tab completion is
available for file paths, slash commands, model keys after `/switch`,
renderer names after `/renderer`, and session IDs. Press `Ctrl+J` (or `Escape` then `Enter`) for
multi-line submission.

---

## Core Features

- **Powerful Autonomy:** Real-world toolset: `read_file`, `write_file`, `edit_file` (surgical diffs), `run_command`, `grep_files`, and `list_files`.
- **Session Persistence:** Conversations saved as JSONL in `~/.copane/sessions/`.
- **Filetype-Aware:** Mappings for Python/JS/TS: `<leader>tx` (Explain), `<leader>tt` (Test), `<leader>tr` (Refactor).
- **Multi-Model Support:** Switch between DeepSeek, OpenAI, Gemini, local Ollama models, or any OpenAI ChatCompletions compatible model. 
- **Pluggable Renderers:** Control how responses appear - streaming ANSI replace (default), 
raw passthrough, inline markdown, or rich terminal formatting. Switch on the fly with `/renderer <key>`.

---

## Configuration

### API Keys
Create `~/.copane.env` with your keys (`DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, etc.).

### Models
| Key | Model | Type | API Key Required |
|-----|-------|------|------------------|
| `deepseek-chat` | DeepSeek Chat | API | `DEEPSEEK_API_KEY` |
| `gpt-4o` | OpenAI GPT-4o | API | `OPENAI_API_KEY` |
| `local-ollama` | Ollama (gemma4:26b) | Local | None |

### Renderers
Control display via `COPANE_RENDERER` in `~/.copane.env`:
- `raw_replace` (Default): Lightweight, in-place formatting.
- `regex`: Zero-dependency markdown-style colors.
- `markdown_it`: Streaming CommonMark (needs `markdown-it-py`).
- `rich_buffer`: Rich terminal formatting (needs `rich`).

---

## Project Structure

```
copane/
├── plugin/             ← Vim plugin entry point
├── python/
│   └── src/
│       └── copane/
│           ├── app.py          ← Main AI application
│           ├── ui.py           ← Layout & status panel
│           ├── tmux_agent.py   ← Agent runner, tool loop
│           ├── model_config.py ← Model definitions
│           ├── session_store.py ← JSONL persistence
│           ├── renderers/      ← Pluggable renderers
│           └── tools/          ← read, write, edit, grep, run...
├── ftplugin/           ← Python/JS/TS mappings
├── install.sh          ← Standalone install
└── setup_python.sh     ← Python venv setup
```

---

## Troubleshooting

### "Python setup failed"
Ensure the `venv` module is available (e.g., `sudo apt install python3-venv` on Ubuntu).

### "Not inside a tmux session"
Integrated UI requires tmux. Start with `tmux` or `tmux new`.

## License
MIT License — see LICENSE file for details.
