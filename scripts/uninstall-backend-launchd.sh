#!/usr/bin/env bash
set -euo pipefail

LABEL="com.lani.backend"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true

if [ -f "$PLIST" ]; then
  rm -f "$PLIST"
  echo "Removed launchd plist: $PLIST"
else
  echo "No installed plist found at $PLIST"
fi

echo "Launchd backend service uninstalled"