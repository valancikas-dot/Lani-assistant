#!/usr/bin/env bash
# deploy-desktop.sh – kopijuoja paskutinį Tauri build į /Applications ir perkrauna Dock
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$SCRIPT_DIR/../apps/desktop"
RELEASE_APP="$DESKTOP_DIR/src-tauri/target/release/bundle/macos/Lani.app"

if [ ! -d "$RELEASE_APP" ]; then
  echo "[ERROR] Release build nerastas: $RELEASE_APP"
  echo "Pirma paleisk:  bash scripts/build-desktop.sh"
  exit 1
fi

echo "==> Diegiu $RELEASE_APP → /Applications/Lani.app …"
cp -R "$RELEASE_APP" /Applications/Lani.app
killall Dock 2>/dev/null || true
echo "✓ Lani.app atnaujinta. Paleisk iš Dock arba Spotlight."
