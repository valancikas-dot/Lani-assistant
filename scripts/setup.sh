#!/usr/bin/env bash
# setup.sh – one-time project setup script
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."

echo "════════════════════════════════════════"
echo "  Personal AI Assistant – Setup"
echo "════════════════════════════════════════"

# ── Backend ───────────────────────────────────────────────────────────────
echo ""
echo "==> Setting up Python backend..."
cd "$ROOT/services/orchestrator"

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install poetry
poetry install

if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> Created .env — edit ALLOWED_DIRECTORIES before running."
fi

# ── Frontend ──────────────────────────────────────────────────────────────
echo ""
echo "==> Setting up frontend..."
cd "$ROOT/apps/desktop"
npm install

echo ""
echo "════════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  Run backend:  cd services/orchestrator && source .venv/bin/activate && uvicorn app.main:app --reload"
echo "  Run frontend: cd apps/desktop && npm run dev"
echo "  Run Tauri:    cd apps/desktop && npm run tauri:dev"
echo "════════════════════════════════════════"
