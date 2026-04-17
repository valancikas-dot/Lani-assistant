#!/usr/bin/env bash
# build-desktop.sh – build the Lani desktop app for local distribution
#
# Prerequisites
# ─────────────
#   macOS:   Xcode command-line tools, Rust toolchain, Node.js ≥18
#   Windows: Visual Studio Build Tools, Rust toolchain, Node.js ≥18
#   Linux:   gcc, libwebkit2gtk-4.0-dev, libssl-dev, Node.js ≥18
#
# Usage
# ─────
#   ./scripts/build-desktop.sh              # release build
#   ./scripts/build-desktop.sh --debug      # debug build (faster, unoptimised)
#
# Output
# ──────
#   apps/desktop/src-tauri/target/release/bundle/
#     macos/   → Lani.app + Lani.dmg
#     windows/ → Lani_0.1.0_x64_en-US.msi / .exe
#     linux/   → lani_0.1.0_amd64.AppImage / .deb

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/.."
DESKTOP_DIR="$ROOT_DIR/apps/desktop"
DEBUG_FLAG=""

# ── Parse args ───────────────────────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --debug) DEBUG_FLAG="--debug" ;;
    --help)
      echo "Usage: $0 [--debug]"
      exit 0
      ;;
  esac
done

echo "╔══════════════════════════════════════════╗"
echo "║  Lani Desktop Build                      ║"
echo "╚══════════════════════════════════════════╝"

# ── 1. Install JS dependencies ────────────────────────────────────────────────
echo ""
echo "==> Installing npm dependencies…"
cd "$DESKTOP_DIR"
npm install

# ── 2. Type-check ─────────────────────────────────────────────────────────────
echo ""
echo "==> Type checking TypeScript…"
npx tsc --noEmit
echo "    ✓ No type errors"

# ── 3. Run frontend tests ──────────────────────────────────────────────────────
echo ""
echo "==> Running frontend tests…"
npx vitest run
echo "    ✓ Tests passed"

# ── 4. Tauri build ────────────────────────────────────────────────────────────
echo ""
if [ -n "$DEBUG_FLAG" ]; then
  echo "==> Building Tauri app (debug)…"
else
  echo "==> Building Tauri app (release)…"
fi

npx tauri build $DEBUG_FLAG

# ── 5. Install to /Applications (macOS only) ─────────────────────────────────
if [[ "$(uname)" == "Darwin" ]]; then
  APP_SRC="$DESKTOP_DIR/src-tauri/target/${DEBUG_FLAG:+debug}${DEBUG_FLAG:-release}/bundle/macos/Lani.app"
  if [ -d "$APP_SRC" ]; then
    echo ""
    echo "==> Installing Lani.app → /Applications …"
    cp -R "$APP_SRC" /Applications/Lani.app
    # Bounce the Dock so the icon refreshes immediately
    killall Dock 2>/dev/null || true
    echo "    ✓ Lani.app installed. Relaunch from Dock or Spotlight."
  fi
fi

# ── 6. Print output location ──────────────────────────────────────────────────
BUNDLE_DIR="$DESKTOP_DIR/src-tauri/target/${DEBUG_FLAG:+debug}${DEBUG_FLAG:-release}/bundle"
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Build complete                          ║"
echo "╚══════════════════════════════════════════╝"
echo "Output: $BUNDLE_DIR"
echo ""
ls "$BUNDLE_DIR" 2>/dev/null || echo "(bundle directory not found – check Tauri output above)"
