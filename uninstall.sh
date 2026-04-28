#!/bin/bash
# copane — Uninstall Script
# Removes all files created by install.sh and setup_python.sh
#
# Note: This does NOT remove the plugin manager's copy of copane.
# To remove the Vim/Neovim plugin, remove it from your plugin manager config.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Configuration (mirrors install.sh)
PYTHON_VENV_DIR="${HOME}/.copane/venv"
ENV_FILE="${HOME}/.copane.env"
BIN_FILE="${HOME}/.local/bin/copane"
TMUX_CONF="${HOME}/.tmux.conf"

confirm() {
    read -p "$1 (y/N): " -n 1 -r
    echo
    [[ $REPLY =~ ^[Yy]$ ]]
}

usage() {
    cat << EOF
copane Uninstall Script

Usage: $0 [OPTIONS]

Options:
  -h, --help      Show this help
  -y, --yes       Non-interactive (remove everything)
  --keep-env      Keep ~/.copane.env config file
  --keep-venv     Keep Python virtual environment
  --keep-bin      Keep ~/.local/bin/copane
  --keep-tmux     Keep tmux config changes
  --dry-run       Show what would be removed without deleting

Examples:
  $0              # Interactive uninstall
  $0 -y           # Remove everything without asking
  $0 --keep-env   # Remove everything except .env
  $0 --dry-run    # Preview only
EOF
}

main() {
    local AUTO_YES=false
    local KEEP_ENV=false
    local KEEP_VENV=false
    local KEEP_BIN=false
    local KEEP_TMUX=false
    local DRY_RUN=false

    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help) usage; exit 0 ;;
            -y|--yes) AUTO_YES=true; shift ;;
            --keep-env) KEEP_ENV=true; shift ;;
            --keep-venv) KEEP_VENV=true; shift ;;
            --keep-bin) KEEP_BIN=true; shift ;;
            --keep-tmux) KEEP_TMUX=true; shift ;;
            --dry-run) DRY_RUN=true; shift ;;
            *) print_error "Unknown option: $1"; usage; exit 1 ;;
        esac
    done

    print_info "Starting copane uninstall..."
    echo

    local REMOVED_ANY=false

    # 1. Virtual environment
    if [[ -d "$PYTHON_VENV_DIR" ]] && [[ "$KEEP_VENV" == false ]]; then
        if $DRY_RUN; then
            print_info "[DRY RUN] Would remove: $PYTHON_VENV_DIR"
            REMOVED_ANY=true
        elif $AUTO_YES || confirm "Remove virtual environment at $PYTHON_VENV_DIR?"; then
            rm -rf "$PYTHON_VENV_DIR"
            print_success "Removed: $PYTHON_VENV_DIR"
            REMOVED_ANY=true
        fi
    fi

    # 2. .env file (shared with the Vim/Neovim plugin — removing it will break the plugin)
    if [[ -f "$ENV_FILE" ]] && [[ "$KEEP_ENV" == false ]]; then
        if $DRY_RUN; then
            print_info "[DRY RUN] Would remove: $ENV_FILE"
            REMOVED_ANY=true
        elif $AUTO_YES; then
            rm -f "$ENV_FILE"
            print_success "Removed: $ENV_FILE"
            REMOVED_ANY=true
        else
            print_warning "~/.copane.env is shared with the Vim/Neovim plugin."
            print_warning "Removing it will break the plugin until you recreate it."
            echo ""
            if confirm "Remove ~/.copane.env?"; then
                rm -f "$ENV_FILE"
                print_success "Removed: $ENV_FILE"
                REMOVED_ANY=true
            else
                print_info "Skipped: $ENV_FILE"
            fi
        fi
    fi

    # 3. copane executable
    if [[ -f "$BIN_FILE" ]] && [[ "$KEEP_BIN" == false ]]; then
        if $DRY_RUN; then
            print_info "[DRY RUN] Would remove: $BIN_FILE"
            REMOVED_ANY=true
        elif $AUTO_YES || confirm "Remove $BIN_FILE?"; then
            rm -f "$BIN_FILE"
            print_success "Removed: $BIN_FILE"
            REMOVED_ANY=true
        fi
    fi

    # 4. tmux config snippet
    if [[ -f "$TMUX_CONF" ]] && [[ "$KEEP_TMUX" == false ]]; then
        if grep -q "copane" "$TMUX_CONF" 2>/dev/null; then
            if $DRY_RUN; then
                print_info "[DRY RUN] Would remove copane entries from $TMUX_CONF"
                REMOVED_ANY=true
            elif $AUTO_YES || confirm "Remove copane entries from $TMUX_CONF?"; then
                if [[ "$(uname)" == "Darwin" ]]; then
                    sed -i '' '/^# copane/,/^$/d' "$TMUX_CONF"
                else
                    sed -i '/^# copane/,/^$/d' "$TMUX_CONF"
                fi
                print_success "Removed copane entries from $TMUX_CONF"
                REMOVED_ANY=true
            fi
        fi
    fi

    echo
    if [[ "$REMOVED_ANY" == false ]]; then
        print_info "Nothing to remove — copane was not installed via install.sh/setup_python.sh"
    elif $DRY_RUN; then
        print_info "Dry run complete. Run without --dry-run to actually remove."
    else
        print_success "Uninstall complete!"
        echo ""
        print_info "To also remove the Vim/Neovim plugin, delete it from your plugin manager."
    fi
}

main "$@"
