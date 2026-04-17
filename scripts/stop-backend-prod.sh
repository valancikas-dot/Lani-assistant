#!/usr/bin/env bash
set -euo pipefail

PIDFILE="/tmp/lani-backend.pid"
LABEL="com.lani.backend"

if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)/$LABEL" && echo "Stopped launchd backend service ($LABEL)"
fi

if [ -f "$PIDFILE" ]; then
  PID=$(cat "$PIDFILE")
  if ps -p "$PID" >/dev/null 2>&1; then
    kill "$PID" && echo "Stopped backend (pid $PID)" || echo "Failed to stop pid $PID"
  else
    echo "No process with pid $PID"
  fi
  rm -f "$PIDFILE"
elif ! launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  echo "No pidfile found and launchd service is not loaded"
fi
