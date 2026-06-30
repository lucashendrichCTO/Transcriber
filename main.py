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
import webview

# Desktop mode captures audio in Python (sounddevice), NOT via the WebView's
# getUserMedia. WKWebView's getUserMedia returns silent PCM inside an embedded
# app, which is why live transcription came back empty. Set before importing
# app so the server reports the right capture mode to the client. Must precede
# the `from app import …` below, which reads this at import time.
os.environ["TRANSCRIBER_DESKTOP"] = "1"

from app import app as fastapi_app

PORT = 8765

_LOG_DIR = os.path.expanduser("~/Library/Logs/Transcriber")
_LOG_PATH = os.path.join(_LOG_DIR, "desktop.log")


def log(msg: str) -> None:
    """Append a timestamped line to the desktop log (GUI apps have no stdout)."""
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        with open(_LOG_PATH, "a") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass
    print(msg, flush=True)


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

    log("=== Transcriber desktop launching ===")

    if _instance_already_running(PORT):
        log(f"another instance already serving port {PORT} — activating it and exiting")
        try:
            subprocess.run(["open", "-b", "com.lucashendrich.transcriber"], timeout=5)
        except Exception:
            pass
        sys.exit(0)

    server_thread = threading.Thread(target=_start_server, daemon=True, name="uvicorn")
    server_thread.start()

    if not _wait_for_port(PORT):
        raise RuntimeError(f"Server did not start on port {PORT} within 15 s")
    log(f"server up on port {PORT}")

    window = webview.create_window(
        title="Transcriber",
        url=f"http://127.0.0.1:{PORT}",
        width=880,
        height=740,
        min_size=(640, 520),
        background_color="#0f0f0f",
    )

    # Persist WKWebView data (cookies, granted permissions) across launches so
    # the microphone grant from first use survives app restarts.
    storage = os.path.expanduser("~/Library/Application Support/Transcriber")
    os.makedirs(storage, exist_ok=True)

    # Audio is captured in Python via sounddevice (see TRANSCRIBER_DESKTOP above),
    # not the WebView's getUserMedia — embedded WKWebView getUserMedia returns
    # silent PCM. macOS prompts for microphone access (NSMicrophoneUsageDescription
    # + the audio-input entitlement) when sounddevice opens the input stream.
    log("opening window (Python/sounddevice handles microphone capture)")
    webview.start(storage_path=storage)
    # The daemon server_thread exits automatically with the process.
