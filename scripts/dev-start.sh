#!/usr/bin/env bash
# dev-start.sh – one-command local development start for Lani
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/.."

echo "==> Running readiness check..."
bash "$SCRIPT_DIR/check-readiness.sh" || true

echo "==> Starting integrated local dev flow..."
exec bash "$SCRIPT_DIR/launch-lani.sh"