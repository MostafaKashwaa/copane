#!/usr/bin/env bash
set -euo pipefail

# standalone installer for copane
# prerequisites: python3, python3-venv, tmux, git

REPO="https://github.com/MostafaKashwaa/copane"
INSTALL_DIR="${HOME}/.copane"
VENV_DIR="${INSTALL_DIR}/venv"
BIN_DIR="${HOME}/.local/bin"

# 1. verify prerequisites
command -v python3 >/dev/null 2>&1 || { echo "Error: python3 required"; exit 1; }
python3 -c "import venv" >/dev/null 2>&1 || { echo "Error: python3-venv required (sudo apt install python3-venv)"; exit 1; }
command -v git >/dev/null 2>&1 || { echo "Error: git required"; exit 1; }
command -v tmux >/dev/null 2>&1 || { echo "Error: tmux required"; exit 1; }

# 2. clone repo
if [ -d "$INSTALL_DIR" ]; then
  if [ ! -d "$INSTALL_DIR/.git" ]; then
    echo "Warning: $INSTALL_DIR exists but is not a git repository."
    read -p "Do you want to remove it and clone copane? (y/n) " yn
    case $yn in
        [Yy]* ) 
          rm -rf "$INSTALL_DIR"
          echo "Cloning copane to $INSTALL_DIR..."
          git clone --depth 1 "$REPO" "$INSTALL_DIR"
          ;;
        * ) echo "Aborting installation."; exit 1;;
    esac
  else
    
    echo "Updating copane..."
    cd "$INSTALL_DIR" && git pull
  fi
else
    echo "Cloning copane to $INSTALL_DIR..."
    git clone --depth 1 "$REPO" "$INSTALL_DIR"
fi

# 3. create venv and install package
echo "Setting up Python virtual environment..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet -e "$INSTALL_DIR/python"

# 4. install copane command
mkdir -p "$BIN_DIR"
cat > "${BIN_DIR}/copane" << 'SCRIPT'
#!/usr/bin/env bash
exec "${HOME}/.copane/venv/bin/python3" -m copane.app "$@"
SCRIPT
chmod +x "${BIN_DIR}/copane"

# 5. create default env file
if [ ! -f "${HOME}/.copane.env" ]; then
    cp "$INSTALL_DIR/.env.example" "${HOME}/.copane.env"
    echo "Created ~/.copane.env — edit it with your API keys."
fi

echo ""
echo "copane installed successfully!"
echo "Make sure $BIN_DIR is in your PATH:"
echo "  echo 'export PATH=\"\$PATH:\$HOME/.local/bin\"' >> ~/.bashrc"
echo "  source ~/.bashrc"
echo ""
echo "Then run: copane"
