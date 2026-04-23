# copane

An AI coding assistant that runs in a tmux pane, integrated with Vim/Neovim
for seamless code review, explanation, refactoring, and testing.

## Features

- **AI-Powered Code Assistance**: Get explanations, reviews, refactoring
  suggestions, and test generation
- **tmux Integration**: Runs in a dedicated tmux pane with persistent
  sessions — survives editor restarts
- **Vim/Neovim Integration**: Send code directly from your editor with
  leader mappings (`<leader>to` to open, `<leader>ts` to send, etc.)
- **Multiple AI Models**: Support for DeepSeek, OpenAI GPT-4o, and local
  Ollama models
- **File Inclusion**: Reference files in your queries using `@filename`
- **Zero Manual Setup**: Python virtual environment and dependencies are
  installed automatically on first use
- **Filetype-Aware**: Language-specific commands for Python, JavaScript,
  TypeScript (see `ftplugin/`)

## Installation

### With a Plugin Manager (Recommended)

#### vim-plug
```vim
" In ~/.vimrc or ~/.config/nvim/init.vim
Plug 'MostafaKashwaa/copane'
```

Then `:PlugInstall`. That's it — Python setup happens automatically
the first time you run `:CopaneOpen`.

#### lazy.nvim (Neovim)
```lua
{
  'MostafaKashwaa/copane',
  init = function()
    -- Optional: configure before load
    vim.g.copane_split_direction = 'horizontal'
  end,
}
```

#### dein.vim
```vim
call dein#add('MostafaKashwaa/copane')
```

### Manual Installation (for Vim/Neovim)

```bash
git clone https://github.com/MostafaKashwaa/copane.git \
  ~/.vim/pack/plugins/start/copane
```

Or for Neovim:
```bash
git clone https://github.com/MostafaKashwaa/copane.git \
  ~/.local/share/nvim/site/pack/plugins/start/copane
```

The first time you run `:CopaneOpen`, the Python environment is set up
automatically. Or run `:CopaneSetupPython` to do it immediately.

### Standalone Terminal Installation (without Vim)

If you only want the AI agent from the terminal without Vim integration:

```bash
git clone https://github.com/MostafaKashwaa/copane.git
cd copane
./install.sh
copane     # Launch interactive AI agent
```

This creates a virtual environment, installs dependencies, and adds
the `copane` command to `~/.local/bin/`.

## Configuration

### 1. Set up API Keys

Copy the example env file and add your keys:

```bash
cp .env.example ~/.copane.env
# Edit ~/.copane.env — add your DEEPSEEK_API_KEY (or OPENAI_API_KEY)
```

Required for API-based models. The `local-ollama` model works without keys.

### 2. Configure Vim/Neovim (Optional)

The plugin works out of the box with these default mappings:

| Mapping | Action |
|---------|--------|
| `<leader>to` | Open/focus the AI pane |
| `<leader>tc` | Close the AI pane |
| `<leader>tt` | Toggle between editor and AI pane |
| `<leader>ts` | Send current buffer to AI |
| `<leader>ts` (visual) | Send visual selection to AI |
| `<leader>tm` | Show current AI model info |
| `<leader>tM` | List available models |
| `<leader>th` | Show help |

(`<leader>` is `\` by default in Vim, `Space` in many Neovim setups)

Change the prefix in your vimrc:

```vim
" Use , instead of <leader>t
let g:copane_mapping_prefix = ','
```

### 3. Filetype-Specific Mappings

For Python and JavaScript/TypeScript files, additional commands are
available in `ftplugin/`:

| Command | Action |
|---------|--------|
| `:TmuxAgentPythonExplain` | Explain the buffer |
| `:TmuxAgentPythonTest` | Write unit tests |
| `:TmuxAgentPythonRefactor` | Refactor the code |
| `:TmuxAgentJSExplain` | Explain JS/TS code |
| `:TmuxAgentJSTest` | Write Jest tests |
| `:TmuxAgentJSRefactor` | Refactor JS/TS code |

### 4. Vim Options Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `g:copane_python_path` | `python3` | Python executable |
| `g:copane_default_model` | `deepseek-chat` | Default AI model |
| `g:copane_env_file` | `~/.copane.env` | Path to env file |
| `g:copane_venv_dir` | `~/.vim/copane-venv` | Python venv location |
| `g:copane_tmux_pane_name` | `copane` | tmux pane title |
| `g:copane_split_direction` | `vertical` | `vertical`, `horizontal`, or `below` |
| `g:copane_split_size` | `33%` | tmux pane size |
| `g:copane_pane_scope` | `session` | `session` (one pane per tmux session) or `window` |
| `g:copane_auto_open` | `0` | Auto-open for Python/JS/Go/Rust files |
| `g:copane_mapping_prefix` | `<leader>t` | Prefix for all mappings |
| `g:copane_debug` | `0` | Show debug messages |
| `g:copane_start_command` | `''` | Custom command for the tmux pane |

## Usage

### In Vim/Neovim

1. Open the AI pane: `<leader>to` or `:CopaneOpen`
2. Select code in visual mode
3. Send it: `<leader>ts` or `:'<,'>CopaneSend`
4. The AI responds in the tmux pane

Or send the whole buffer: `:CopaneSend`

### In tmux (when copane pane is focused)

Type questions directly. Special commands:

| Command | Action |
|---------|--------|
| `/models` | List available models |
| `/switch <name>` | Switch model |
| `/modelinfo` | Show current model info |
| `/clear` | Clear conversation history |
| `/help` | Show help |

Include files in your query with `@filename`.

### From Terminal

```bash
# Interactive session
copane

# With environment file
copane --env-file ~/.copane.env

# With specific model
copane --model gpt-4o

# List models and exit
copane --list-models
```

## Models

| Model | Type | API Key Required |
|-------|------|------------------|
| `deepseek-chat` | DeepSeek API | `DEEPSEEK_API_KEY` |
| `gpt-4o` | OpenAI API | `OPENAI_API_KEY` |
| `local-ollama` | Local Ollama | None (requires `ollama serve`) |

Switch models in the copane pane:
```
/switch gpt-4o
```

## Project Structure

```
copane/
├── plugin/
│   └── copane.vim          ← Plugin entry point (commands, mappings)
├── autoload/
│   └── tmux_agent.vim      ← Core tmux pane management logic
├── python/
│   ├── app.py              ← Main AI application
│   ├── tmux_agent.py       ← Agent implementation
│   ├── tools.py            ← Agent tool definitions
│   ├── file_utils.py       ← File utilities
│   ├── term_styles.py      ← Terminal styling
│   └── check_deps.py       ← Dependency checker
├── ftplugin/
│   ├── python.vim          ← Python-specific mappings
│   └── javascript.vim      ← JavaScript/TypeScript mappings
├── after/ftplugin/
│   └── python.vim          ← Extended Python commands
├── doc/
│   └── tmux_agent.txt      ← Help file (:help copane)
├── install.sh              ← Standalone terminal install
├── setup_python.sh         ← Python setup script (shared)
├── uninstall.sh            ← Cleanup script
├── pyproject.toml          ← Python packaging
├── .env.example            ← Environment template
└── README.md               ← This file
```

## Dependencies

- **tmux** (required) — for the AI pane
- **Python 3.12+** (required) — runs the AI agent
- **Vim 8+ or Neovim 0.5+** — for editor integration

Python packages (installed automatically into a venv):

- `prompt-toolkit` — Interactive command line interface
- `openai-agents` — AI agent framework
- `langsmith` — Tracing and monitoring
- `python-dotenv` — Environment variable management
- `autopep8` — Code formatting
- `pynvim` — Neovim remote plugin support

## Troubleshooting

### "Python environment not ready"
Run `:CopaneSetupPython` to force reinstall.

### "copane command not found" (terminal)
```bash
# Add ~/.local/bin to PATH
echo 'export PATH="$PATH:$HOME/.local/bin"' >> ~/.bashrc
source ~/.bashrc
```

### Vim mappings not working
```vim
:echo exists('g:loaded_copane')
" Should return 1
:echo g:copane_mapping_prefix
" Should show your prefix
```

### "Not inside a tmux session"
copane requires tmux. Start tmux first: `tmux` or `tmux new`.

### Debug mode
```vim
let g:copane_debug = 1
" Or press leader th to see help
:CopaneDebug
```

## License

MIT License — see LICENSE file for details.

## Acknowledgments

- Built with [openai-agents](https://github.com/openai/openai-agents-python)
- Inspired by various AI coding assistants
