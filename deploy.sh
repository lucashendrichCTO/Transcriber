#!/usr/bin/env bash
# deploy.sh — test → build → install pipeline for Transcriber.app
#
# Usage:
#   ./deploy.sh               run tests, then build and install
#   ./deploy.sh --test-only   run tests only, no build
#   ./deploy.sh --build-only  skip tests, build and install immediately

set -e
cd "$(dirname "$0")"

TEST=1
BUILD=1

for arg in "$@"; do
  case "$arg" in
    --test-only)  BUILD=0 ;;
    --build-only) TEST=0  ;;
  esac
done

# ── Activate venv ────────────────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
  echo "No .venv found — run ./run.sh once first to create the environment."
  exit 1
fi
source .venv/bin/activate

# ── Tests ────────────────────────────────────────────────────────────────────
if [ "$TEST" = "1" ]; then
  echo ""
  echo "── Python tests ────────────────────────────────────────────────────────"
  python -m pytest tests/ -v --tb=short
  echo ""
  echo "── JS tests ────────────────────────────────────────────────────────────"
  npm test
  echo ""
  echo "All tests passed."
fi

# ── Build + install ──────────────────────────────────────────────────────────
if [ "$BUILD" = "1" ]; then
  echo ""
  echo "── Building and installing Transcriber.app ─────────────────────────────"
  ./make_app.sh --install
fi
