#!/usr/bin/env bash
# launch-lani.sh – starts the Lani backend + frontend and opens the UI
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCHESTRATOR_DIR="$SCRIPT_DIR/../services/orchestrator"
DESKTOP_DIR="$SCRIPT_DIR/../apps/desktop"

# ── 1. Start backend ──────────────────────────────────────────────────────────
echo "==> Starting Lani backend..."
cd "$ORCHESTRATOR_DIR"

if [ ! -f .env ]; then
  echo "==> Creating .env from .env.example"
  cp .env.example .env
fi

if [ -d ".venv" ]; then
  source .venv/bin/activate
else
  echo "[ERROR] Missing backend virtualenv at services/orchestrator/.venv"
  echo "Run: bash scripts/setup.sh"
  exit 1
fi

if ! command -v uvicorn >/dev/null 2>&1; then
  echo "[ERROR] uvicorn not found in the active environment"
  echo "Run: bash scripts/setup.sh"
  exit 1
fi

# Run backend in background, store PID
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
echo "    Backend PID: $BACKEND_PID"

cleanup() {
  kill "$BACKEND_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

# ── 2. Install frontend deps if needed ────────────────────────────────────────
cd "$DESKTOP_DIR"
if [ ! -d "node_modules" ]; then
  echo "==> Installing npm dependencies..."
  npm install
fi

# ── 3. Wait for backend health, then open browser ───────────────────────────
echo "==> Waiting for backend health check..."
for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
  echo "[ERROR] Backend did not become healthy within 30 seconds"
  exit 1
fi

echo "==> Opening Lani at http://localhost:1420 ..."
open "http://localhost:1420" &

# ── 4. Start Vite dev server (foreground – closing terminal stops everything) ──
echo "==> Starting Vite dev server..."
npm run dev
