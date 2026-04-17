#!/usr/bin/env bash
# check-readiness.sh – quick local readiness check for Lani
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/.."
BACKEND_DIR="$ROOT_DIR/services/orchestrator"
FRONTEND_DIR="$ROOT_DIR/apps/desktop"

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  echo "[PASS] $1"
}

warn() {
  WARN_COUNT=$((WARN_COUNT + 1))
  echo "[WARN] $1"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  echo "[FAIL] $1"
}

backend_healthy() {
  curl -fsS http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1
}

echo "==> Lani readiness check"

[[ -d "$BACKEND_DIR" ]] && pass "Backend directory exists" || fail "Missing backend directory"
[[ -d "$FRONTEND_DIR" ]] && pass "Frontend directory exists" || fail "Missing frontend directory"

[[ -d "$BACKEND_DIR/.venv" ]] && pass "Backend virtualenv exists" || fail "Missing backend virtualenv (.venv)"
[[ -d "$FRONTEND_DIR/node_modules" ]] && pass "Frontend dependencies installed" || warn "Frontend node_modules missing"

if [[ -f "$BACKEND_DIR/.env" ]]; then
  pass "Backend .env exists"
  if grep -q '^ALLOWED_DIRECTORIES_RAW=' "$BACKEND_DIR/.env"; then
    if grep -Eq '^ALLOWED_DIRECTORIES_RAW=.+$' "$BACKEND_DIR/.env"; then
      pass "ALLOWED_DIRECTORIES_RAW configured"
    else
      warn "ALLOWED_DIRECTORIES_RAW is empty (file tools will be blocked)"
    fi
  else
    warn "ALLOWED_DIRECTORIES_RAW missing from .env (file tools will be blocked)"
  fi

  if grep -Eq '^(OPENAI_API_KEY|ANTHROPIC_API_KEY)=.+$' "$BACKEND_DIR/.env"; then
    pass "At least one LLM key configured"
  else
    warn "No LLM API key configured"
  fi

  grep -Eq '^SECRET_KEY=.+$' "$BACKEND_DIR/.env" && pass "SECRET_KEY configured" || warn "SECRET_KEY missing"
  grep -Eq '^CONNECTOR_ENCRYPTION_KEY=.+$' "$BACKEND_DIR/.env" && pass "CONNECTOR_ENCRYPTION_KEY configured" || warn "CONNECTOR_ENCRYPTION_KEY missing"
else
  fail "Backend .env missing"
fi

if [[ -f "$HOME/Library/LaunchAgents/com.lani.backend.plist" ]]; then
  if launchctl print "gui/$(id -u)/com.lani.backend" >/dev/null 2>&1; then
    pass "launchd backend service installed"
  else
    warn "launchd backend plist exists but service is not loaded"
  fi
else
  warn "launchd backend service not installed"
fi

BACKEND_READY=0
for _ in 1 2 3 4 5; do
  if backend_healthy; then
    BACKEND_READY=1
    break
  fi
  sleep 1
done

if [[ $BACKEND_READY -eq 1 ]]; then
  pass "Backend health endpoint reachable"
else
  if launchctl print "gui/$(id -u)/com.lani.backend" >/dev/null 2>&1; then
    warn "Backend launchd service is loaded but health endpoint is not reachable yet"
  else
    warn "Backend is not currently running on 127.0.0.1:8000"
  fi
fi

echo ""
echo "Summary: $PASS_COUNT pass, $WARN_COUNT warn, $FAIL_COUNT fail"

if [[ $FAIL_COUNT -gt 0 ]]; then
  exit 1
fi

exit 0