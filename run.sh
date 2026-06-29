#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

PORT=8765
URL="http://127.0.0.1:${PORT}"
VERBOSE_MODE=0

# Parse flags
for arg in "$@"; do
  case "$arg" in
    --verbose|-v) VERBOSE_MODE=1 ;;
  esac
done

# Find Python 3.9+
PY=""
for candidate in python3 /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3; do
  if command -v "$candidate" &>/dev/null; then
    PY="$candidate"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "Python 3 not found. Install via: brew install python"
  exit 1
fi

# Create venv if missing
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment…"
  $PY -m venv .venv
fi

source .venv/bin/activate

# Install / upgrade deps quietly
echo "Checking dependencies…"
pip install -q -r requirements.txt

# Free the port if a stale server is still holding it
STALE=$(lsof -nP -iTCP:${PORT} -sTCP:LISTEN -t 2>/dev/null || true)
if [ -n "$STALE" ]; then
  echo "Port ${PORT} was in use by PID(s): $STALE — stopping them…"
  echo "$STALE" | xargs kill -9 2>/dev/null || true
  sleep 1
fi

echo ""
echo "────────────────────────────────────────────────────────"
echo "  Transcriber is starting."
echo ""
echo "  Open this URL in your browser (note the port :${PORT}):"
echo ""
echo "      ${URL}"
echo ""
if [ "$VERBOSE_MODE" = "1" ]; then
echo "  Verbose logging is ON."
echo ""
fi
echo "  Press Ctrl+C to stop the server."
echo "  First transcription downloads the Whisper model (~142 MB)."
echo "────────────────────────────────────────────────────────"
echo ""

# Auto-open the browser to the correct URL (2s delay so the server is up)
( sleep 5 && command -v open >/dev/null && open "${URL}" ) &

if [ "$VERBOSE_MODE" = "1" ]; then
  VERBOSE=1 python -m uvicorn app:app --host 127.0.0.1 --port $PORT --log-level info
else
  python -m uvicorn app:app --host 127.0.0.1 --port $PORT --log-level warning
fi
