# copane

An AI coding assistant that runs in a tmux pane, integrated with Vim/Neovim
for seamless code review, explanation, refactoring, and testing.

## Features

- **AI-Powered Code Assistance**: Get explanations, reviews, refactoring
  suggestions, and test generation
- **tmux Integration**: Runs in a dedicated tmux pane with persistent
  sessions — survives editor restarts
- **Vim/Neovim Integration**: Send code directly from your editor with
  leader mappings
- **Multiple AI Models**: Support for DeepSeek, OpenAI GPT-4o, and local
  Ollama models — switch at runtime with `/switch <name>`
- **File Inclusion**: Reference files in your queries using `@filename`
- **Filetype-Aware**: Language-specific commands for Python and JavaScript
- **Zero Manual Setup**: Python virtual environment is created automatically
  on first `:CopaneOpen`

## Installation

### With vim-plug

```vim
" In ~/.vimrc or ~/.config/nvim/init.vim
Plug 'MostafaKashwaa/copane'
```

Then `:PlugInstall`. The Python environment is set up automatically the
first time you run `:CopaneOpen`.

### With lazy.nvim (Neovim)

```lua
{
  'MostafaKashwaa/copane',
  init = function()
    -- Optional: configure before load
    vim.g.copane_split_direction = 'horizontal'
  end,
}
```

### Manual Installation (Vim 8+ packages)

```bash
git clone https://github.com/MostafaKashwaa/copane.git \
  ~/.vim/pack/plugins/start/copane
```

Or for Neovim:

```bash
git clone https://github.com/MostafaKashwaa/copane.git \
  ~/.local/share/nvim/site/pack/plugins/start/copane
```

### Standalone Terminal (without Vim)

```bash
curl -fsSL https://raw.githubusercontent.com/MostafaKashwaa/copane/main/install.sh | bash
```

This installs the `copane` command to `~/.local/bin/`. Make sure
`~/.local/bin` is in your PATH (add `export PATH="$PATH:$HOME/.local/bin"`
to `~/.bashrc` if not).

Prerequisites: `python3`, `python3-venv`, `git`, `tmux`.

Then configure your API keys (see [Configuration](#configuration)).

## Configuration

### 1. API Keys

Create `~/.copane.env` with your API keys:

```bash
cp .env.example ~/.copane.env
# Edit ~/.copane.env — add DEEPSEEK_API_KEY (or OPENAI_API_KEY, etc.)
```

Or open it from inside Vim with:

```
:CopaneEditSecrets
```

The local `local-ollama` model works without any API key.

### 2. Model Configuration

Model settings (which models are available, API endpoints, which one is
selected) are stored in:

```
~/.config/tmux-agent/model_config.json
```

Open it from inside Vim with:

```
:CopaneEditConfig
```

This file is auto-generated on first run with defaults for DeepSeek,
OpenAI, and local Ollama. You can edit it to add custom endpoints
(e.g., Groq, Anthropic, a local vLLM server).

Switch models at runtime inside the copane pane:

```
/switch gpt-4o
/switch local-ollama
```

### 3. Vim/Neovim Options

The plugin works out of the box. All mappings use the prefix
`<leader>t` by default. Change it in your vimrc:

```vim
let g:copane_mapping_prefix = ',c'
```

#### All configuration variables

| Variable | Default | Description |
|----------|---------|-------------|
| `g:copane_python_path` | `python3` | Python executable |
| `g:copane_default_model` | `deepseek-chat` | Default AI model |
| `g:copane_env_file` | `~/.copane.env` | Path to .env file |
| `g:copane_venv_dir` | `<plugin>/python/.venv` | Python venv location |
| `g:copane_tmux_pane_name` | `copane` | tmux pane title |
| `g:copane_split_direction` | `vertical` | `vertical` or `horizontal` |
| `g:copane_split_size` | `33%` | tmux pane size |
| `g:copane_pane_scope` | `session` | `session` or `window` |
| `g:copane_auto_open` | `0` | Auto-open for Python/JS/Go files |
| `g:copane_mapping_prefix` | `<leader>t` | Prefix for all mappings |
| `g:copane_show_banner` | `1` | Show banner on app start |
| `g:copane_debug` | `0` | Show debug messages |
| `g:copane_start_command` | `''` | Custom command for the tmux pane |
| `g:copane_enable_ftplugin` | `1` | Load filetype-specific plugins |
| `g:copane_enable_neovim_async` | `1` | Use Neovim async features |
| `g:copane_no_suggestions` | `0` | Suppress startup messages |

## Mappings

Default prefix is `<leader>t` (usually `\t` in Vim, ` <Space>t` in
many Neovim setups).

| Mapping | Mode | Action |
|---------|------|--------|
| `<leader>to` | normal | Open/focus the AI pane |
| `<leader>tc` | normal | Close the AI pane |
| `<leader>tt` | normal | Toggle between editor and AI pane |
| `<leader>ts` | normal | Send current buffer to AI |
| `<leader>ts` | visual | Send visual selection to AI |
| `<leader>tm` | normal | Show current AI model info |
| `<leader>tM` | normal | List available models |
| `<leader>te` | normal | Edit secrets file (`~/.copane.env`) |
| `<leader>tE` | normal | Edit model config (`model_config.json`) |
| `<leader>th` | normal | Show help |

Disable all default mappings with:

```vim
let g:copane_no_mappings = 1
" Then define your own:
nnoremap <leader>ca :CopaneOpen<CR>
```

## Commands

| Command | Description |
|---------|-------------|
| `:CopaneOpen` | Open/focus the AI pane |
| `:CopaneClose` | Close the AI pane |
| `:CopaneToggle` | Toggle between editor and AI pane |
| `:CopaneSend` | Send current buffer to AI |
| `:'<,'>CopaneSend` | Send visual selection to AI |
| `:CopaneModelInfo` | Show current AI model |
| `:CopaneSwitchModel <key>` | Switch to a different model |
| `:CopaneListModels` | List all available models |
| `:CopaneClearHistory` | Clear conversation history |
| `:CopaneEditSecrets` | Edit `~/.copane.env` |
| `:CopaneEditConfig` | Edit `model_config.json` |
| `:CopaneSetupPython` | (Re)install Python dependencies |
| `:CopaneHelp` | Show help summary |
| `:CopaneDebug` | Show debug information |

## Usage

### In Vim/Neovim

1. Open the AI pane: `<leader>to` or `:CopaneOpen`
2. Select code in visual mode
3. Send it: `<leader>ts` or `:'<,'>CopaneSend`
4. The AI responds in the tmux pane

Or send the whole buffer with `:CopaneSend`.

### In the copane pane (when focused)

Type questions directly. Special commands:

| Command | Action |
|---------|--------|
| `/models` | List available models |
| `/switch <name>` | Switch model |
| `/modelinfo` | Show current model info |
| `/clear` | Clear conversation history |
| `/help` | Show help |

Include files in your query with `@filename`. Example:

```
review this @main.py for any bugs
```

### From Terminal

```bash
# Interactive session
copane

# With environment file
copane --env-file ~/.copane.env

# Quick action modes
copane --mode explain --file main.py
copane --mode test --text "def add(a,b): return a+b"

# Model management
copane --list-models
copane --switch gpt-4o
copane --model-info
```

## Filetype Plugins

When editing Python or JavaScript/TypeScript files, additional mappings
are available in `ftplugin/`:

| Mapping | Mode | Action |
|---------|------|--------|
| `<leader>ta` | normal/visual | Send code to AI |
| `<leader>te` | normal/visual | Explain code |
| `<leader>tt` | normal/visual | Write tests |
| `<leader>tr` | normal/visual | Refactor code |
| `<leader>td` | normal/visual | Debug code |

For TypeScript files, an additional mapping is available:

| Mapping | Action |
|---------|--------|
| `<leader>tty` | Add TypeScript types |

These filetype mappings use the **same** prefix as the global ones
(`g:copane_mapping_prefix`, default `<leader>t`).

## Models

| Key | Model | Type | API Key Required |
|-----|-------|------|------------------|
| `deepseek-chat` | DeepSeek Chat | API | `DEEPSEEK_API_KEY` |
| `gpt-4o` | OpenAI GPT-4o | API | `OPENAI_API_KEY` |
| `local-ollama` | Ollama (gemma4:26b) | Local | None |

Switch at runtime inside the copane pane:

```
/switch gpt-4o
```

Or add custom models by editing `~/.config/tmux-agent/model_config.json`.

## Project Structure

```
copane/
├── plugin/
│   └── copane.vim              ← Plugin entry point (commands, mappings, setup)
├── autoload/
│   ├── copane.vim              ← Config file editing functions
│   └── tmux_agent.vim          ← Core tmux pane management
├── python/
│   └── src/
│       └── copane/
│           ├── __init__.py
│           ├── app.py          ← Main AI application (entry point)
│           ├── tmux_agent.py   ← Agent + ModelConfig logic
│           ├── tools.py        ← Tool definitions (read file, run command, etc.)
│           ├── file_utils.py   ← File completion & expansion
│           ├── term_styles.py  ← Terminal styling and colors
│           └── check_deps.py   ← Dependency checker
├── ftplugin/
│   ├── python.vim              ← Python-specific mappings
│   └── javascript.vim          ← JavaScript/TypeScript mappings
├── after/ftplugin/
│   └── python.vim              ← Extended Python compatibility
├── doc/
│   └── copane.txt              ← Vim help file (:help copane)
├── install.sh                  ← Standalone terminal install
├── setup_python.sh             ← Python venv setup script (plugin)
├── uninstall.sh                ← Cleanup script
├── python/pyproject.toml       ← Python packaging
├── .env.example                ← Environment template
└── README.md                   ← This file
```

## Dependencies

- **tmux** (required) — for the AI pane
- **Python 3.12+** (required) — runs the AI agent
- **Vim 8+ or Neovim 0.5+** — for editor integration
- **uv** (optional) — fast Python package installer (if not present, falls
  back to python3 + pip)
- **git** (required for install.sh) — clones the repository

Python packages (installed automatically into the venv):

- `prompt-toolkit` — Interactive command line interface
- `openai-agents` — AI agent framework
- `langsmith` — Tracing and monitoring
- `python-dotenv` — Environment variable management
- `openai` — OpenAI API client

## Troubleshooting

### "Python setup failed" / Virtual environment not created

If `:CopaneOpen` fails with "Python setup failed", the most common cause
is that the `venv` module is not available on your system.

**On Debian / Ubuntu / Linux Mint:**
```bash
sudo apt install python3-venv
```

**On RHEL / Fedora / CentOS:**
```bash
sudo dnf install python3-virtualenv
```

**On Arch Linux / Manjaro:**
```bash
sudo pacman -S python-virtualenv
```

**On openSUSE:**
```bash
sudo zypper install python3-virtualenv
```

After installing, run `:CopaneSetupPython` inside Vim or run the setup
script manually:

```bash
cd ~/.vim/plugged/copane    # or wherever vim-plug installed it
bash setup_python.sh
```

### "Python environment not ready"
Run `:CopaneSetupPython` to force reinstall.

### "copane command not found" (terminal)
```bash
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
:let g:copane_debug = 1
:CopaneDebug
```

## License

MIT License — see LICENSE file for details.
