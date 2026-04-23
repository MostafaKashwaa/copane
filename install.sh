#!/bin/bash
# copane — Standalone Installation Script
# Installs copane for use from the terminal (without Vim/Neovim).
#
# If you use a plugin manager (vim-plug, lazy.nvim, etc.), you don't need
# this script — just add the plugin and the Vim plugin handles Python setup
# automatically on first use.
#
# Usage:
#   bash install.sh                    # full standalone install
#   bash install.sh --no-tmux          # skip tmux config
#   bash install.sh --no-venv          # skip venv creation (if already done)
#   bash install.sh --help             # show all options

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Configuration
PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_VENV_DIR="${HOME}/.vim/copane-venv"
ENV_FILE="${HOME}/.copane.env"
BIN_DIR="${HOME}/.local/bin"
PYTHON_MIN_VERSION="3.12"

# ── Helpers ──────────────────────────────────────────────────────────────

command_exists() { command -v "$1" >/dev/null 2>&1; }

# ── Steps ────────────────────────────────────────────────────────────────

check_python() {
    if ! command_exists python3; then
        print_error "python3 not found"
        exit 1
    fi
    local pyver
    pyver=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    IFS='.' read -r -a MIN <<< "$PYTHON_MIN_VERSION"
    IFS='.' read -r -a CUR <<< "$pyver"
    for i in 0 1; do
        if [[ ${CUR[i]} -lt ${MIN[i]} ]]; then
            print_error "Python $pyver is too old. Required: $PYTHON_MIN_VERSION+"
            exit 1
        elif [[ ${CUR[i]} -gt ${MIN[i]} ]]; then
            break
        fi
    done
    print_info "Found Python $pyver"
}

create_venv() {
    if [[ -d "$PYTHON_VENV_DIR" ]]; then
        print_warning "Virtual environment already exists at $PYTHON_VENV_DIR"
        read -p "Recreate it? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$PYTHON_VENV_DIR"
        else
            print_info "Using existing virtual environment"
            return 0
        fi
    fi

    print_info "Creating virtual environment..."
    python3 -m venv "$PYTHON_VENV_DIR"
    print_success "Virtual environment created at $PYTHON_VENV_DIR"
}

install_deps() {
    print_info "Installing Python dependencies..."
    source "${PYTHON_VENV_DIR}/bin/activate"
    pip install --upgrade pip -q
    pip install -e "$PLUGIN_DIR" -q
    deactivate
    print_success "Python dependencies installed"
}

create_env_file() {
    if [[ ! -f "$ENV_FILE" ]]; then
        cat > "$ENV_FILE" << 'EOF'
# copane Configuration
# Add your API keys here

# DeepSeek API (recommended)
# DEEPSEEK_API_KEY=your_deepseek_api_key_here

# OpenAI API (optional)
# OPENAI_API_KEY=your_openai_api_key_here

# Default model: deepseek-chat
# Available: deepseek-chat, gpt-4o, local-ollama
EOF
        print_info "Created $ENV_FILE — please add your API keys"
    else
        print_info "$ENV_FILE already exists, skipping"
    fi
}

create_executable() {
    mkdir -p "$BIN_DIR"

    cat > "${BIN_DIR}/copane" << 'EOF'
#!/bin/bash
# copane — AI Coding Agent (terminal launcher)

VENV="${HOME}/.vim/copane-venv"
ENV_FILE="${HOME}/.copane.env"

# Find the plugin directory (relative to this script's expected location)
# Try common locations
for dir in "$(dirname "$0")/.." "$HOME/.vim/plugged/copane" "$HOME/.local/share/nvim/site/pack/plugins/start/copane" "$HOME/.vim/pack/plugins/start/copane"; do
    if [[ -f "$dir/python/app.py" ]]; then
        PLUGIN_DIR="$dir"
        break
    fi
done

if [[ -z "$PLUGIN_DIR" ]]; then
    echo "Error: copane plugin directory not found." >&2
    echo "Make sure copane is installed via your plugin manager or run install.sh" >&2
    exit 1
fi

# Activate virtual environment
if [[ -d "$VENV" ]]; then
    source "$VENV/bin/activate"
fi

# Load environment variables
if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

# Run the agent
exec python3 "$PLUGIN_DIR/python/app.py" "$@"
EOF

    chmod +x "${BIN_DIR}/copane"
    print_success "Created executable at ${BIN_DIR}/copane"

    if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
        print_warning "$BIN_DIR is not in PATH"
        print_info "Add to ~/.bashrc: export PATH=\"\$PATH:$BIN_DIR\""
    fi
}

setup_tmux() {
    if ! command_exists tmux; then
        print_warning "tmux not found, skipping tmux integration"
        return 0
    fi

    local tmux_conf="${HOME}/.tmux.conf"
    local snippet="# copane: open AI agent in a split pane
bind-key a split-window -h \"copane\"
"

    if [[ -f "$tmux_conf" ]]; then
        if grep -q "copane" "$tmux_conf" 2>/dev/null; then
            print_info "tmux config already has copane entry"
        else
            echo "" >> "$tmux_conf"
            echo "$snippet" >> "$tmux_conf"
            print_success "Added copane to $tmux_conf (Ctrl-b a to open)"
        fi
    else
        echo "$snippet" > "$tmux_conf"
        print_success "Created $tmux_conf with copane binding (Ctrl-b a to open)"
    fi
}

verify() {
    if [[ ! -d "$PYTHON_VENV_DIR" ]]; then
        print_error "Virtual environment missing"
        exit 1
    fi
    if "${PYTHON_VENV_DIR}/bin/python3" -c "import sys; sys.path.insert(0, '${PLUGIN_DIR}'); from python.tmux_agent import agent; print('OK')" &>/dev/null; then
        print_success "Python environment verified"
    else
        print_error "Python environment not working"
        exit 1
    fi
}

# ── Usage ────────────────────────────────────────────────────────────────

usage() {
    cat << EOF
copane — Standalone Installation Script

Installs copane for terminal use (without Vim/Neovim plugin manager).

Usage: bash install.sh [OPTIONS]

Options:
  -h, --help      Show this help
  --no-venv       Skip virtual environment creation
  --no-deps       Skip Python dependencies installation
  --no-tmux       Skip tmux configuration
  --no-env        Skip .env file creation

Examples:
  bash install.sh              # Full standalone install
  bash install.sh --no-tmux    # Install without tmux keybinding

Note: Vim/Neovim users should use their plugin manager instead.
      The plugin handles Python setup automatically on first use.
EOF
}

# ── Main ─────────────────────────────────────────────────────────────────

main() {
    local SKIP_VENV=false
    local SKIP_DEPS=false
    local SKIP_TMUX=false
    local SKIP_ENV=false

    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help) usage; exit 0 ;;
            --no-venv) SKIP_VENV=true; shift ;;
            --no-deps) SKIP_DEPS=true; shift ;;
            --no-tmux) SKIP_TMUX=true; shift ;;
            --no-env) SKIP_ENV=true; shift ;;
            *) print_error "Unknown option: $1"; usage; exit 1 ;;
        esac
    done

    echo ""
    print_info "copane — Standalone Installation"
    echo ""

    check_python

    if [[ "$SKIP_VENV" == false ]]; then
        create_venv || exit 1
    fi
    if [[ "$SKIP_DEPS" == false ]]; then
        install_deps || exit 1
    fi

    create_env_file
    create_executable

    if [[ "$SKIP_TMUX" == false ]]; then
        setup_tmux
    fi

    verify

    echo ""
    print_success "Installation complete!"
    echo ""
    echo "  Run:  copane"
    echo "  Edit: $ENV_FILE (add your API keys)"
    echo ""
    echo "For Vim/Neovim integration, add to your plugin manager:"
    echo "  Plug 'username/copane'"
    echo ""
}

main "$@"
