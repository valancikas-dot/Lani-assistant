#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCHESTRATOR_DIR="$SCRIPT_DIR/../services/orchestrator"
# Prefer macOS standard logs folder
LOG_DIR="$HOME/Library/Logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/lani-backend.log"
PIDFILE="/tmp/lani-backend.pid"

cd "$ORCHESTRATOR_DIR" || exit 1

# Ensure .env exists
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
  fi
fi

# Activate venv if present
if [ -d ".venv" ]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi

# If port 8000 already in use, backend is running — skip start
if lsof -i :8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port 8000 already in use — backend running. Skipping start." >> "$LOG"
  exit 0
fi

# If PID file exists and process is alive, do not start another backend
if [ -f "$PIDFILE" ]; then
  EXISTING_PID=$(cat "$PIDFILE" 2>/dev/null || echo "")
  if [ -n "$EXISTING_PID" ] && ps -p "$EXISTING_PID" >/dev/null 2>&1; then
    echo "Backend already running (pid $EXISTING_PID). Exiting start script." >> "$LOG"
    exit 0
  else
    # stale pidfile
    rm -f "$PIDFILE" || true
  fi
fi

# Rotate log if larger than 10MB
if [ -f "$LOG" ]; then
  MAX_SIZE=$((10 * 1024 * 1024))
  SIZE=$(stat -f%z "$LOG" 2>/dev/null || stat -c%s "$LOG" 2>/dev/null || echo 0)
  if [ "$SIZE" -gt "$MAX_SIZE" ]; then
    mv "$LOG" "$LOG.$(date +%s)"
  fi
fi

# Database safety: backup and dedupe potential duplicate rows that can cause UNIQUE constraint errors
DB_PATH="$ORCHESTRATOR_DIR/assistant.db"
if [ -f "$DB_PATH" ]; then
  # Backup DB before any change
  cp "$DB_PATH" "$DB_PATH.bak.$(date +%s)" || true
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$DB_PATH" <<'SQL'
BEGIN TRANSACTION;
DELETE FROM user_settings
WHERE rowid NOT IN (
  SELECT min(rowid) FROM user_settings GROUP BY id
);
COMMIT;
SQL
  fi
fi

# Start uvicorn using venv python as module to avoid shebang issues
if [ -x "$ORCHESTRATOR_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="$ORCHESTRATOR_DIR/.venv/bin/python"
  nohup "$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >"$LOG" 2>&1 &
  echo $! > "$PIDFILE"
else
  if command -v uvicorn >/dev/null 2>&1; then
    nohup uvicorn app.main:app --host 127.0.0.1 --port 8000 >"$LOG" 2>&1 &
    echo $! > "$PIDFILE"
  else
    echo "uvicorn not found in venv or PATH" >&2
    exit 1
  fi
fi

# Give a moment for process to start
sleep 1

# Print status
if ps -p $(cat "$PIDFILE") >/dev/null 2>&1; then
  echo "Backend started (pid $(cat \"$PIDFILE\")), logs: $LOG"
  exit 0
else
  echo "Failed to start backend. See $LOG" >&2
  exit 1
fi
