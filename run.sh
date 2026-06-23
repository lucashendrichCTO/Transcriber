#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# Prefer Homebrew Python 3 on macOS
if command -v /opt/homebrew/bin/python3 &>/dev/null; then
  PY=/opt/homebrew/bin/python3
elif command -v python3 &>/dev/null; then
  PY=python3
else
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
echo ""

python app.py
