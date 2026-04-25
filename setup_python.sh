#!/usr/bin/env bash
# copane — Python Environment Setup Script
# Creates a virtual environment inside the plugin's python/ folder
# and installs the copane package in editable mode.
#
# Prefers uv (fast), falls back to python3 -m venv + pip (portable).
#
# This script is called by Vim automatically (post-update hook) or manually.
# Usage: bash setup_python.sh

set -euo pipefail

# --- Colors ---
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
# Plugin root = where this script lives
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Python project directory (contains pyproject.toml, uv.lock, src/)
PYTHON_DIR="${PLUGIN_DIR}/python"

# Virtual environment lives INSIDE the python directory
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
    if command -v uv &>/dev/null; then
        print_info "Found uv ($(uv --version 2>/dev/null || echo 'unknown'))"
        return 0
    fi
    print_info "uv not found — will use venv + pip instead"
    return 1
}

# --- uv-based setup (fast path) ---
setup_with_uv() {
    cd "$PYTHON_DIR"

    if [[ -d ".venv" ]]; then
        print_info "Existing virtual environment found. Running uv sync..."
    else
        print_info "Creating virtual environment via uv..."
    fi

    # If uv.lock exists, use --frozen for reproducible installs.
    # Otherwise, let uv resolve dependencies fresh.
    if [[ -f "uv.lock" ]]; then
        uv sync --frozen
    else
        uv sync
    fi

    print_success "Dependencies installed into ${VENV_DIR} (via uv)"
}

# --- venv + pip setup (fallback path) ---
setup_with_venv() {
    cd "$PYTHON_DIR"

    if [[ -d ".venv" ]]; then
        print_info "Existing virtual environment found. Updating..."
    else
        print_info "Creating virtual environment using python3 -m venv..."

        # Try creating the venv; capture stderr for a helpful error message
        local venv_output
        venv_output=$(python3 -m venv ".venv" 2>&1) || {
            print_error "Failed to create virtual environment with python3 -m venv."
            echo ""
            echo "  This usually means the python3-venv package is missing."
            echo "  On Debian/Ubuntu, install it with:"
            echo ""
            echo "    sudo apt install python3-venv"
            echo ""
            echo "  On RHEL/Fedora:"
            echo ""
            echo "    sudo dnf install python3-virtualenv"
            echo ""
            echo "  On Arch Linux:"
            echo ""
            echo "    sudo pacman -S python-virtualenv"
            echo ""
            echo "  For other systems, see:"
            echo "    https://docs.python.org/3/library/venv.html"
            echo ""
            echo "  Original error:"
            echo "    $venv_output"
            echo ""
            exit 1
        }

        print_success "Virtual environment created at ${VENV_DIR}"
    fi

    # Upgrade pip inside the venv — older systems ship a stale pip
    print_info "Upgrading pip..."
    .venv/bin/python3 -m pip install --upgrade pip -q

    # Install the package in editable mode
    print_info "Installing copane package and dependencies..."
    .venv/bin/python3 -m pip install -e . -q

    print_success "Dependencies installed into ${VENV_DIR} (via venv + pip)"
}

verify() {
    print_info "Verifying installation..."

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

    # 2. Check for uv — fast path or fallback
    if check_uv; then
        setup_with_uv
    else
        setup_with_venv
    fi

    # 3. Quick sanity check
    verify

    echo ""
    print_success "Setup complete!"
    echo ""
    echo "  Virtual environment: ${VENV_DIR}"
    echo "  Activate temporarily:  source ${VENV_DIR}/bin/activate"
    echo "  Run app:               ${VENV_DIR}/bin/python3 -m copane.app"
    echo ""
}

main
