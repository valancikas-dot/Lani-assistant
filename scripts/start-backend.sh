#!/usr/bin/env bash
# start-backend.sh – starts the FastAPI orchestrator in development mode
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCHESTRATOR_DIR="$SCRIPT_DIR/../services/orchestrator"

echo "==> Starting Personal AI Assistant backend..."
cd "$ORCHESTRATOR_DIR"

# Create .env from example if it doesn't exist
if [ ! -f .env ]; then
  echo "==> Creating .env from .env.example"
  cp .env.example .env
fi

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
  source .venv/bin/activate
else
  echo "[ERROR] Python virtualenv not found at services/orchestrator/.venv"
  echo "Run: bash scripts/setup.sh"
  exit 1
fi

if ! command -v uvicorn >/dev/null 2>&1; then
  echo "[ERROR] uvicorn not found in the active environment"
  echo "Run: bash scripts/setup.sh"
  exit 1
fi

echo "==> Starting uvicorn on http://127.0.0.1:8000"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload &
BACKEND_PID=$!

cleanup() {
  kill "$BACKEND_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

echo "==> Waiting for backend health check..."
for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
    echo "==> Backend is healthy on http://127.0.0.1:8000"
    wait "$BACKEND_PID"
    exit $?
  fi
  sleep 1
done

echo "[ERROR] Backend did not become healthy within 30 seconds"
exit 1
