#!/bin/bash
# copane — Python Environment Setup Script
# This script creates the virtual environment and installs Python dependencies.
# It is called automatically by the Vim plugin on first use, or can be run manually.
#
# Usage:
#   bash setup_python.sh                    # install to default location
#   bash setup_python.sh /path/to/venv      # install to custom location
#
# This script does NOT copy Vim plugin files — the plugin manager handles that.

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

# Determine plugin directory (where this script lives)
PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"

# Default venv location (can be overridden)
DEFAULT_VENV="${HOME}/.vim/copane-venv"
VENV_DIR="${1:-$DEFAULT_VENV}"

# Python minimum version
PYTHON_MIN_VERSION="3.12"

check_python() {
    if ! command -v python3 &>/dev/null; then
        print_error "python3 not found"
        exit 1
    fi

    local pyver
    pyver=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    
    IFS='.' read -r -a MIN_PARTS <<< "$PYTHON_MIN_VERSION"
    IFS='.' read -r -a CUR_PARTS <<< "$pyver"

    for i in 0 1; do
        if [[ ${CUR_PARTS[i]} -lt ${MIN_PARTS[i]} ]]; then
            print_error "Python $pyver is too old. Required: $PYTHON_MIN_VERSION+"
            exit 1
        elif [[ ${CUR_PARTS[i]} -gt ${MIN_PARTS[i]} ]]; then
            break
        fi
    done

    print_info "Found Python $pyver"
}

create_venv() {
    if [[ -d "$VENV_DIR" ]]; then
        print_warning "Virtual environment already exists at $VENV_DIR"
        read -p "Recreate it? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$VENV_DIR"
        else
            print_info "Using existing virtual environment"
            return 0
        fi
    fi

    print_info "Creating virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
    print_success "Virtual environment created"
}

install_deps() {
    print_info "Installing Python dependencies..."

    source "${VENV_DIR}/bin/activate"

    pip install --upgrade pip -q

    if [[ -f "$PLUGIN_DIR/pyproject.toml" ]]; then
        pip install -e "$PLUGIN_DIR" -q
        print_success "Dependencies installed from pyproject.toml"
    else
        print_error "pyproject.toml not found in $PLUGIN_DIR"
        deactivate
        exit 1
    fi

    deactivate
}

verify() {
    print_info "Verifying installation..."

    local test_code="import sys; sys.path.insert(0, '${PLUGIN_DIR}'); from python.tmux_agent import agent; print('OK')"
    if "${VENV_DIR}/bin/python3" -c "$test_code" &>/dev/null; then
        print_success "Python environment ready at $VENV_DIR"
    else
        print_error "Verification failed — something went wrong"
        exit 1
    fi
}

main() {
    echo ""
    print_info "copane — Python Environment Setup"
    echo ""

    check_python
    create_venv
    install_deps
    verify

    echo ""
    print_success "Setup complete!"
    echo ""
    echo "  Virtual environment: $VENV_DIR"
    echo "  Activate:            source $VENV_DIR/bin/activate"
    echo "  Run agent:           $VENV_DIR/bin/python3 $PLUGIN_DIR/python/app.py"
    echo ""
}

main
