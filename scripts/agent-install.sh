#!/usr/bin/env bash
# agent-install.sh — Install the Beacon telemetry agent natively on macOS.
#
# This script is for development/manual installs before the Homebrew formula
# is published. It creates a venv, installs beacon, sets up directories,
# and optionally loads the launchd plist for auto-start.
#
# Usage:
#   ./scripts/agent-install.sh           # install only
#   ./scripts/agent-install.sh --start   # install and start via launchd

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv-agent"
PLIST_SRC="${PROJECT_ROOT}/homebrew/com.beacon.agent.plist"
PLIST_NAME="com.beacon.agent"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
PLIST_DEST="${LAUNCH_AGENTS_DIR}/${PLIST_NAME}.plist"
LOG_DIR="${HOME}/Library/Logs/Beacon"
DATA_DIR="${HOME}/.local/share/beacon"

info()  { printf "\033[32m==>\033[0m %s\n" "$1"; }
warn()  { printf "\033[33m==>\033[0m %s\n" "$1"; }
error() { printf "\033[31m==>\033[0m %s\n" "$1" >&2; }

# --- Pre-flight checks ---
if [[ "$(uname -s)" != "Darwin" ]]; then
    error "This script is for macOS only."
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    error "python3 not found. Install via: brew install python@3.11"
    exit 1
fi

# --- Create directories ---
info "Creating directories..."
mkdir -p "$LOG_DIR" "$DATA_DIR" "$LAUNCH_AGENTS_DIR"

# --- Create virtual environment ---
if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment at ${VENV_DIR}..."
    python3 -m venv "$VENV_DIR"
else
    info "Virtual environment already exists at ${VENV_DIR}"
fi

# --- Install beacon ---
info "Installing beacon into venv..."
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip
"${VENV_DIR}/bin/pip" install --quiet -e "${PROJECT_ROOT}"

# Verify install
if ! "${VENV_DIR}/bin/beacon" --help &>/dev/null; then
    error "beacon CLI not found after install. Check pyproject.toml entry points."
    exit 1
fi
info "beacon CLI installed: ${VENV_DIR}/bin/beacon"

# --- Install launchd plist ---
if [[ -f "$PLIST_SRC" ]]; then
    info "Installing launchd plist..."

    # Resolve placeholders in the plist template
    HOMEBREW_PREFIX="$(brew --prefix 2>/dev/null || echo "/opt/homebrew")"
    sed \
        -e "s|HOMEBREW_PREFIX/bin/beacon|${VENV_DIR}/bin/beacon|g" \
        -e "s|HOMEBREW_PREFIX/var/beacon|${DATA_DIR}|g" \
        -e "s|HOMEBREW_PREFIX/bin:|${VENV_DIR}/bin:|g" \
        -e "s|HOME_DIR|${HOME}|g" \
        "$PLIST_SRC" > "$PLIST_DEST"

    info "Plist installed: ${PLIST_DEST}"
else
    warn "Plist template not found at ${PLIST_SRC}, skipping launchd setup."
fi

# --- Optionally start the agent ---
if [[ "${1:-}" == "--start" ]]; then
    # Unload first in case it was previously loaded
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
    launchctl load "$PLIST_DEST"
    info "Agent loaded via launchd. Check logs at: ${LOG_DIR}/agent.log"
else
    info "Install complete. To start the agent:"
    echo "  launchctl load ${PLIST_DEST}"
    echo ""
    echo "Or run manually:"
    echo "  ${VENV_DIR}/bin/beacon telemetry start"
    echo ""
    echo "To auto-start on next run:"
    echo "  $0 --start"
fi

info "Done."
