#!/usr/bin/env bash
set -euo pipefail

LABEL="com.lani.backend"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ORCHESTRATOR_DIR="$PROJECT_DIR/services/orchestrator"
TEMPLATE_PLIST="$PROJECT_DIR/apps/desktop/src-tauri/launchd/com.lani.backend.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
INSTALLED_PLIST="$LAUNCH_AGENTS_DIR/$LABEL.plist"
LOG="$HOME/Library/Logs/lani-backend.log"
PYTHON_BIN="$ORCHESTRATOR_DIR/.venv/bin/python"

mkdir -p "$LAUNCH_AGENTS_DIR" "$HOME/Library/Logs"

if [ ! -f "$TEMPLATE_PLIST" ]; then
    echo "Launchd plist template not found: $TEMPLATE_PLIST" >&2
    exit 1
fi

if [ ! -x "$PYTHON_BIN" ]; then
    echo "Backend virtualenv python not found: $PYTHON_BIN" >&2
    exit 1
fi

if [ ! -f "$ORCHESTRATOR_DIR/.env" ]; then
    echo "Missing backend .env at $ORCHESTRATOR_DIR/.env" >&2
    exit 1
fi

if [ -f "$LOG" ] && [ "$(stat -f%z "$LOG" 2>/dev/null || echo 0)" -gt 10485760 ]; then
    mv "$LOG" "$LOG.old"
fi

sed \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    -e "s|__ORCHESTRATOR_DIR__|$ORCHESTRATOR_DIR|g" \
    -e "s|__PYTHON_BIN__|$PYTHON_BIN|g" \
    -e "s|__LOG_PATH__|$LOG|g" \
    "$TEMPLATE_PLIST" > "$INSTALLED_PLIST"

launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
launchctl disable "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
launchctl unload "$INSTALLED_PLIST" >/dev/null 2>&1 || true
launchctl load -w "$INSTALLED_PLIST"
launchctl start "$LABEL" >/dev/null 2>&1 || true

echo "[$(date)] Backend launchd service installed and started: $LABEL" >> "$LOG"
echo "Installed plist: $INSTALLED_PLIST"
