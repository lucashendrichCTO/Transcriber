"""
main.py — desktop entry point for Transcriber.

Starts the FastAPI server in a daemon thread, waits for it to accept
connections, then opens a native macOS WKWebView window via pywebview.
The process exits when the window is closed (standard red × button).

For CLI / developer use, run the server directly with run.sh instead.
"""

import multiprocessing
import os
import socket
import subprocess
import sys
import threading
import time

import uvicorn

from logutil import make_file_logger

# NOTE: pywebview (`webview`) is imported lazily inside __main__, not here.
# It's a darwin-only dependency, so a top-level import breaks `import main` on
# Linux — which the CI test runner does to test the pure-logic helpers below.

# Desktop mode captures audio in Python (sounddevice), NOT via the WebView's
# getUserMedia. WKWebView's getUserMedia returns silent PCM inside an embedded
# app, which is why live transcription came back empty. Set before importing
# app so the server reports the right capture mode to the client. Must precede
# the `from app import …` below, which reads this at import time.
os.environ["TRANSCRIBER_DESKTOP"] = "1"

# A double-clicked .app bundle never inherits a shell env var, so
# TRANSCRIBER_APP_NAME alone is invisible at runtime for a Finder launch —
# it only ever affected the BUILD (baked into the executable name and
# Info.plist by Transcriber.spec). Without this, every runtime-computed value
# keyed off that env var (port, log dir, storage dir, window title,
# reactivation bundle id) silently fell back to the "Transcriber" default for
# ANY GUI-launched build, beta included — a real bug, not just a risk: a
# beta build launched normally from Finder still bound production's port and
# wrote to production's log file. sys.executable IS reliable here: when
# PyInstaller-frozen, it's the bundle's own Mach-O binary
# (Contents/MacOS/<name>), whatever name the build actually used — no env
# var required. Only fall back to TRANSCRIBER_APP_NAME/"Transcriber" when not
# frozen (e.g. plain `python main.py` during development).
if getattr(sys, "frozen", False):
    APP_NAME = os.path.basename(sys.executable)
else:
    APP_NAME = os.environ.get("TRANSCRIBER_APP_NAME", "Transcriber")
# Re-exported as an env var so app.py (imported next) resolves the same name
# without duplicating the frozen-executable detection above.
os.environ["TRANSCRIBER_APP_NAME"] = APP_NAME

from app import app as fastapi_app

# Matches the name/bundle-id derivation in Transcriber.spec.
BUNDLE_ID = (
    "com.lucashendrich.transcriber"
    if APP_NAME == "Transcriber"
    else f"com.lucashendrich.transcriber.{APP_NAME.lower()}"
)

# A double-clicked .app bundle never inherits a shell env var, so
# TRANSCRIBER_PORT alone can't separate two installed copies (e.g. a beta
# build and production) launched normally from Finder — both would default to
# 8765 and collide, with whichever launches second either failing to bind or
# mistaking the other app for a duplicate instance of itself. Deriving the
# default port from APP_NAME instead means every distinctly-named build is
# isolated out of the box, with no manual env var required.
_DEFAULT_PORT = 8765 if APP_NAME == "Transcriber" else 8766
PORT = int(os.environ.get("TRANSCRIBER_PORT", str(_DEFAULT_PORT)))

log = make_file_logger(APP_NAME)


def _wait_for_port(port: int, timeout: float = 15.0) -> bool:
    """Block until localhost:port accepts connections or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return True
        except OSError:
            time.sleep(0.25)
    return False


def _start_server() -> None:
    uvicorn.run(fastapi_app, host="127.0.0.1", port=PORT, log_level="warning")


def _instance_already_running(port: int) -> bool:
    """True if something already accepts connections on the server port.

    Transcriber is a single-window app. macOS can launch a second copy (e.g.
    while granting microphone access mid-session); without this guard the second
    process fails to bind the port, its server thread dies, and it opens a window
    backed by no server — which then throws a WebSocket error once the first copy
    is closed. Detecting the running instance and bowing out avoids all of that.
    """
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


if __name__ == "__main__":
    # MUST be the very first thing. A library in the audio/transcription stack
    # spawns a worker via multiprocessing; on macOS the default "spawn" method
    # re-executes this frozen binary. Without freeze_support() the child re-runs
    # main.py from the top and launches a SECOND app window (the "app relaunches
    # itself" bug). freeze_support() makes the child run its worker and exit.
    multiprocessing.freeze_support()

    import webview  # darwin-only; imported here so `import main` works on Linux CI

    log("=== Transcriber desktop launching ===")

    if _instance_already_running(PORT):
        log(f"another instance already serving port {PORT} — activating it and exiting")
        try:
            subprocess.run(["open", "-b", BUNDLE_ID], timeout=5)
        except Exception:
            pass
        sys.exit(0)

    server_thread = threading.Thread(target=_start_server, daemon=True, name="uvicorn")
    server_thread.start()

    if not _wait_for_port(PORT):
        raise RuntimeError(f"Server did not start on port {PORT} within 15 s")
    log(f"server up on port {PORT}")

    window = webview.create_window(
        title=APP_NAME,
        url=f"http://127.0.0.1:{PORT}",
        width=880,
        height=740,
        min_size=(640, 520),
        background_color="#0f0f0f",
    )

    # Persist WKWebView data (cookies, granted permissions) across launches so
    # the microphone grant from first use survives app restarts.
    storage = os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
    os.makedirs(storage, exist_ok=True)

    # Audio is captured in Python via sounddevice (see TRANSCRIBER_DESKTOP above),
    # not the WebView's getUserMedia — embedded WKWebView getUserMedia returns
    # silent PCM. macOS prompts for microphone access (NSMicrophoneUsageDescription
    # + the audio-input entitlement) when sounddevice opens the input stream.
    log("opening window (Python/sounddevice handles microphone capture)")
    webview.start(storage_path=storage)
    # The daemon server_thread exits automatically with the process.
