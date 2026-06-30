#!/usr/bin/env bash
# deploy.sh — test → build → verify → install pipeline for Transcriber.app
#
# Usage:
#   ./deploy.sh               run tests, build, install, verify the bundle
#   ./deploy.sh --test-only   run tests only, no build
#   ./deploy.sh --build-only  skip pre-build tests; still verifies the bundle

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

# ── Pre-build tests (logic + real audio capture; bundle tests run post-build) ─
if [ "$TEST" = "1" ]; then
  echo ""
  echo "── Python tests ────────────────────────────────────────────────────────"
  python -m pytest tests/ --ignore=tests/test_bundle.py -v --tb=short
  echo ""
  echo "── JS tests ────────────────────────────────────────────────────────────"
  npm test
  echo ""
  echo "All pre-build tests passed."
fi

# ── Build + install + verify ─────────────────────────────────────────────────
if [ "$BUILD" = "1" ]; then
  echo ""
  echo "── Building and installing Transcriber.app ─────────────────────────────"
  ./make_app.sh --install

  echo ""
  echo "── Bundle integrity tests (verifies TCC code-identity is correct) ──────"
  python -m pytest tests/test_bundle.py -v --tb=short
fi
