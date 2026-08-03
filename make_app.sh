#!/usr/bin/env bash
# Builds Transcriber.app as a genuine signed bundle via PyInstaller.
#
# Why PyInstaller: the bundle's Contents/MacOS/Transcriber is a real Mach-O
# executable with Python embedded.  macOS TCC binds microphone (and BlackHole)
# permission to code identity, so the app must BE the requesting binary — a
# shell script that execs a shared system python gets the request attributed to
# the interpreter, and the mic prompt never fires.
#
# Usage:
#   ./make_app.sh              — build into dist/Transcriber.app
#   ./make_app.sh --install    — build and copy to /Applications
#
# Set TRANSCRIBER_APP_NAME to build/install under a different name (e.g. a
# "Transcriber-beta" test build that won't overwrite the production app).
set -e
cd "$(dirname "$0")"

APP_NAME="${TRANSCRIBER_APP_NAME:-Transcriber}"
APP="dist/$APP_NAME.app"
INSTALL=0
PROJ="$PWD"

for arg in "$@"; do
  case "$arg" in --install|-i) INSTALL=1 ;; esac
done

# ── 1. Environment ────────────────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
  echo "No .venv found — run ./run.sh once first to create the environment."
  exit 1
fi
source .venv/bin/activate

echo "Ensuring build dependencies…"
pip install -q -r requirements.txt
pip install -q pyinstaller

# ── 2. Generate AppIcon.icns from the SVG source ─────────────────────────────
ICON_SVG="$PROJ/icon/AppIcon.svg"
ICON_PNG="$PROJ/icon/AppIcon.png"
ICONSET="$PROJ/icon/AppIcon.iconset"
ICNS="$PROJ/icon/AppIcon.icns"

if [ -f "$ICON_SVG" ]; then
  echo "Generating icon…"
  if command -v rsvg-convert &>/dev/null; then
    rsvg-convert -w 1024 -h 1024 "$ICON_SVG" -o "$ICON_PNG"
  else
    TMPDIR_ICON=$(mktemp -d)
    qlmanage -t -s 1024 -o "$TMPDIR_ICON" "$ICON_SVG" 2>/dev/null || true
    RENDERED=$(find "$TMPDIR_ICON" -name "*.png" | head -1)
    [ -n "$RENDERED" ] && cp "$RENDERED" "$ICON_PNG"
    rm -rf "$TMPDIR_ICON"
  fi

  if [ -f "$ICON_PNG" ]; then
    rm -rf "$ICONSET"; mkdir "$ICONSET"
    sips -z 16   16   "$ICON_PNG" --out "$ICONSET/icon_16x16.png"      >/dev/null
    sips -z 32   32   "$ICON_PNG" --out "$ICONSET/icon_16x16@2x.png"   >/dev/null
    sips -z 32   32   "$ICON_PNG" --out "$ICONSET/icon_32x32.png"      >/dev/null
    sips -z 64   64   "$ICON_PNG" --out "$ICONSET/icon_32x32@2x.png"   >/dev/null
    sips -z 128  128  "$ICON_PNG" --out "$ICONSET/icon_128x128.png"    >/dev/null
    sips -z 256  256  "$ICON_PNG" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
    sips -z 256  256  "$ICON_PNG" --out "$ICONSET/icon_256x256.png"    >/dev/null
    sips -z 512  512  "$ICON_PNG" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
    sips -z 512  512  "$ICON_PNG" --out "$ICONSET/icon_512x512.png"    >/dev/null
    sips -z 1024 1024 "$ICON_PNG" --out "$ICONSET/icon_512x512@2x.png" >/dev/null
    iconutil -c icns "$ICONSET" -o "$ICNS"
    rm -rf "$ICONSET"
    echo "Icon generated."
  fi
else
  echo "Warning: $ICON_SVG not found — building without a custom icon."
fi

# ── 3. Build the bundle ───────────────────────────────────────────────────────
echo "Building $APP_NAME.app with PyInstaller…"
rm -rf build "dist/$APP_NAME.app"
pyinstaller --noconfirm --clean Transcriber.spec

# ── 4. Sign with the microphone entitlement ──────────────────────────────────
# Ad-hoc signature (no Team ID) is fine for local use.  We deliberately do NOT
# use the hardened runtime: it only matters for notarized distribution and adds
# Gatekeeper friction for a locally-built app.  TCC microphone access depends on
# the bundle's code identity + NSMicrophoneUsageDescription, not the runtime.
echo "Signing…"
xattr -cr "$APP"
codesign --force --deep \
  --entitlements entitlements.plist \
  --sign - "$APP"
codesign --verify --deep --strict "$APP" && echo "Signature verified."

# ── 5. Register with LaunchServices + optionally install ─────────────────────
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister

if [ "$INSTALL" = "1" ]; then
  echo "Installing to /Applications…"
  rm -rf "/Applications/$APP_NAME.app"
  cp -R "$APP" "/Applications/$APP_NAME.app"

  # Keep exactly ONE LaunchServices record. The dist/ build copy and the
  # installed copy share one bundle id; two registered copies make Finder render
  # a blank icon (the recurring "icon missing" bug). Unregister the build
  # artifact, register only the installed app, and bounce Finder/Dock so the
  # Applications-folder icon repaints immediately instead of next login.
  "$LSREGISTER" -u "$APP" 2>/dev/null || true
  touch "/Applications/$APP_NAME.app"
  "$LSREGISTER" -f "/Applications/$APP_NAME.app" 2>/dev/null || true
  killall Finder Dock 2>/dev/null || true
  echo "Installed: /Applications/$APP_NAME.app"
else
  # Build-only: register the dist copy so it can be launched in place.
  "$LSREGISTER" -f "$APP" 2>/dev/null || true
fi

echo ""
echo "────────────────────────────────────────────────────────"
echo "  Done: $APP"
if [ "$INSTALL" = "1" ]; then
  echo "  Installed to /Applications/$APP_NAME.app"
else
  echo "  To install:  ./make_app.sh --install"
fi
echo "────────────────────────────────────────────────────────"
