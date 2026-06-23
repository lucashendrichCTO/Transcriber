#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

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
pip install -q -r requirements.txt

echo ""
echo "Starting Transcriber at http://localhost:8765"
echo "Open that URL in your browser, then press Ctrl+C to stop."
echo "Note: The Whisper model (~142 MB) downloads on first use — first transcription will be slower."
echo ""

python app.py
