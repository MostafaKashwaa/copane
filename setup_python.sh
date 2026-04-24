#!/usr/bin/env bash
# copane — Python Environment Setup Script
# Creates a virtual environment inside the plugin’s python/ folder
# and installs the copane package (editable) via uv sync.
#
# This script is called by Vim automatically (post-update hook) or manually.
# Usage: bash setup_python.sh

set -euo pipefail

# --- Colors (unchanged) ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

# --- Determine directories ---
# Plugin root = where this script lives (e.g., ~/.vim/plugged/copane)
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Python project directory (contains pyproject.toml, uv.lock, src/)
PYTHON_DIR="${PLUGIN_DIR}/python"

# Virtual environment will live INSIDE the python directory
VENV_DIR="${PYTHON_DIR}/.venv"

# Minimum Python version
PYTHON_MIN_VERSION="3.12"

# ---------- functions ----------
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

check_uv() {
    if ! command -v uv &>/dev/null; then
        print_error "uv not found. Please install it first:"
        print_info "  curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
    print_info "Found uv ($(uv --version 2>/dev/null || echo 'unknown'))"
}

setup_venv_and_install() {
    # Move into the Python project directory – uv must run from there
    cd "$PYTHON_DIR"

    # If .venv already exists and is functional, we can skip recreation
    # unless the lock file is newer (optional, kept simple for now).
    if [[ -d ".venv" ]]; then
        print_info "Existing virtual environment found. Running uv sync to update..."
    else
        print_info "No virtual environment found. Creating one at ${VENV_DIR}..."
        # uv sync will create the venv if it doesn't exist (when run from a project)
    fi

    # uv sync: creates/updates .venv, installs all deps, and installs the
    # copane package in editable mode (because we are inside the project).
    # --frozen ensures we use exactly the versions from uv.lock.
    uv sync --frozen

    print_success "Dependencies installed into ${VENV_DIR}"
}

verify() {
    print_info "Verifying installation..."

    # Use the venv's python to test importing our package
    local test_code="import copane; print(copane.__file__)"
    if "${VENV_DIR}/bin/python3" -c "$test_code" &>/dev/null; then
        print_success "copane package is importable"
        print_info "Location: $("${VENV_DIR}/bin/python3" -c "$test_code")"
    else
        print_error "Import test failed. Showing error details:"
        "${VENV_DIR}/bin/python3" -c "$test_code" 2>&1 || true
        exit 1
    fi
}

# ---------- main ----------
main() {
    echo ""
    print_info "copane – Python Environment Setup"
    echo ""

    # 1. Prerequisites
    check_python
    check_uv

    # 2. Create/update venv and install package
    setup_venv_and_install

    # 3. Quick sanity check
    verify

    echo ""
    print_success "Setup complete!"
    echo ""
    echo "  Virtual environment: ${VENV_DIR}"
    echo "  Activate temporarily:  source ${VENV_DIR}/bin/activate"
    echo "  Run app:               ${VENV_DIR}/bin/python3 ${PYTHON_DIR}/src/copane/app.py"
    echo ""
}

main
