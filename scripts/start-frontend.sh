#!/usr/bin/env bash
# start-frontend.sh – starts the Vite dev server (React UI only, no Tauri)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$SCRIPT_DIR/../apps/desktop"

echo "==> Starting Personal AI Assistant frontend (Vite dev server)..."
cd "$DESKTOP_DIR"

if [ ! -d "node_modules" ]; then
  echo "==> Installing npm dependencies..."
  npm install
fi

echo "==> Starting Vite on http://localhost:1420"
npm run dev
