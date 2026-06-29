#!/usr/bin/env bash
# Builds Transcriber.app in the current directory.
# Usage:
#   ./make_app.sh              — build only
#   ./make_app.sh --install    — build and move to /Applications

set -e
cd "$(dirname "$0")"

APP_NAME="Transcriber"
APP="$APP_NAME.app"
BUNDLE_ID="com.lucashendrich.transcriber"
INSTALL=0

for arg in "$@"; do
  case "$arg" in --install|-i) INSTALL=1 ;; esac
done

# ── 1. Clean previous build ──────────────────────────────────────────────────
echo "Building $APP…"
rm -rf "$APP"

# ── 2. Directory structure ────────────────────────────────────────────────────
mkdir -p "$APP/Contents/MacOS"
mkdir -p "$APP/Contents/Resources"

# ── 3. Copy project source into Resources/app ────────────────────────────────
mkdir -p "$APP/Contents/Resources/app"
rsync -a \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  --exclude='node_modules' \
  --exclude='*.app' \
  --exclude='.pytest_cache' \
  --exclude='icon' \
  --exclude='make_app.sh' \
  . "$APP/Contents/Resources/app/"

# ── 4. Launcher script ───────────────────────────────────────────────────────
LAUNCHER="$APP/Contents/MacOS/$APP_NAME"
cat > "$LAUNCHER" << 'LAUNCHER_EOF'
#!/usr/bin/env bash
# Launcher for Transcriber.app — sets up the Python environment then hands
# off to main.py, which owns the full lifecycle (server + native window).
APP_SRC="$(cd "$(dirname "$0")/../Resources/app"; pwd)"
LOG_DIR="$HOME/Library/Logs/Transcriber"
LOG="$LOG_DIR/server.log"

mkdir -p "$LOG_DIR"

# Locate Python 3.
PY=""
for candidate in python3 /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3; do
  if command -v "$candidate" &>/dev/null; then
    PY="$candidate"
    break
  fi
done
if [ -z "$PY" ]; then
  osascript -e 'display alert "Transcriber — Python not found" message "Install Python 3 via brew install python, then relaunch." as critical'
  exit 1
fi

cd "$APP_SRC"

# Create venv on first run.
if [ ! -d ".venv" ]; then
  echo "[$(date)] Creating virtual environment…" >> "$LOG" 2>&1
  $PY -m venv .venv >> "$LOG" 2>&1
fi

source .venv/bin/activate

# Install / upgrade deps silently.
pip install -q -r requirements.txt >> "$LOG" 2>&1

# Hand off to main.py — it starts the server, opens the window, and exits
# when the window is closed.  All output is redirected to the log file.
exec python main.py >> "$LOG" 2>&1
LAUNCHER_EOF
chmod +x "$LAUNCHER"

# ── 5. Info.plist ─────────────────────────────────────────────────────────────
cat > "$APP/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundleDisplayName</key>
    <string>$APP_NAME</string>
    <key>CFBundleExecutable</key>
    <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>
    <string>$BUNDLE_ID</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSHumanReadableCopyright</key>
    <string>Lucas Hendrich</string>
</dict>
</plist>
EOF

# ── 6. Generate AppIcon.icns from SVG source ─────────────────────────────────
# Use absolute paths throughout — qlmanage can shift cwd on some macOS versions.
PROJ="$PWD"
ICON_SVG="$PROJ/icon/AppIcon.svg"
ICON_PNG="$PROJ/icon/AppIcon.png"
ICONSET="$PROJ/icon/AppIcon.iconset"

if [ ! -f "$ICON_SVG" ]; then
  echo "Warning: $ICON_SVG not found — skipping icon generation."
else
  echo "Generating icon…"

  # Convert SVG → PNG at 1024×1024 using qlmanage (built-in macOS previewer)
  # We render at 1024 then use sips to produce all required sizes.
  if command -v rsvg-convert &>/dev/null; then
    rsvg-convert -w 1024 -h 1024 "$ICON_SVG" -o "$ICON_PNG"
  else
    # Fallback: use Safari/WebKit via qlmanage to rasterize the SVG
    TMPDIR_ICON=$(mktemp -d)
    qlmanage -t -s 1024 -o "$TMPDIR_ICON" "$ICON_SVG" 2>/dev/null || true
    RENDERED=$(find "$TMPDIR_ICON" -name "*.png" | head -1)
    if [ -n "$RENDERED" ]; then
      cp "$RENDERED" "$ICON_PNG"
      rm -rf "$TMPDIR_ICON"
    else
      rm -rf "$TMPDIR_ICON"
      echo "Warning: could not rasterize SVG — icon will be missing."
      ICON_PNG=""
    fi
  fi

  if [ -n "$ICON_PNG" ] && [ -f "$ICON_PNG" ]; then
    rm -rf "$ICONSET"
    mkdir "$ICONSET"
    sips -z 16   16   "$ICON_PNG" --out "$ICONSET/icon_16x16.png"
    sips -z 32   32   "$ICON_PNG" --out "$ICONSET/icon_16x16@2x.png"
    sips -z 32   32   "$ICON_PNG" --out "$ICONSET/icon_32x32.png"
    sips -z 64   64   "$ICON_PNG" --out "$ICONSET/icon_32x32@2x.png"
    sips -z 128  128  "$ICON_PNG" --out "$ICONSET/icon_128x128.png"
    sips -z 256  256  "$ICON_PNG" --out "$ICONSET/icon_128x128@2x.png"
    sips -z 256  256  "$ICON_PNG" --out "$ICONSET/icon_256x256.png"
    sips -z 512  512  "$ICON_PNG" --out "$ICONSET/icon_256x256@2x.png"
    sips -z 512  512  "$ICON_PNG" --out "$ICONSET/icon_512x512.png"
    sips -z 1024 1024 "$ICON_PNG" --out "$ICONSET/icon_512x512@2x.png"
    iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
    rm -rf "$ICONSET"
    echo "Icon generated."
  fi
fi

# ── 7. Clear quarantine & ad-hoc sign ────────────────────────────────────────
echo "Signing…"
xattr -cr "$APP"
codesign --deep --force --sign - "$APP"

# ── 8. Register with LaunchServices so Finder shows the icon immediately ─────
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "$APP" 2>/dev/null || true

# ── 9. Optionally install to /Applications ───────────────────────────────────
if [ "$INSTALL" = "1" ]; then
  echo "Installing to /Applications…"
  rm -rf "/Applications/$APP"
  cp -R "$APP" "/Applications/$APP"
  echo "Installed: /Applications/$APP"
fi

echo ""
echo "────────────────────────────────────────────────────────"
echo "  Done: $APP"
if [ "$INSTALL" = "1" ]; then
echo "  Installed to /Applications/$APP"
else
echo ""
echo "  To install:   cp -R $APP /Applications/"
echo "  Or run:       ./make_app.sh --install"
fi
echo ""
echo "  To distribute: zip -r Transcriber.zip $APP"
echo "  Recipients:    unzip, then xattr -cr Transcriber.app"
echo "────────────────────────────────────────────────────────"
