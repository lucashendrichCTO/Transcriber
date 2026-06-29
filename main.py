"""
main.py — desktop entry point for Transcriber.

Starts the FastAPI server in a daemon thread, waits for it to accept
connections, then opens a native macOS WKWebView window via pywebview.
The process exits when the window is closed or the Exit button is clicked.

For CLI / developer use, run the server directly with run.sh instead.
"""

import socket
import threading
import time

import uvicorn
import webview

from app import app as fastapi_app

PORT = 8765


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


if __name__ == "__main__":
    server_thread = threading.Thread(target=_start_server, daemon=True, name="uvicorn")
    server_thread.start()

    if not _wait_for_port(PORT):
        raise RuntimeError(f"Server did not start on port {PORT} within 15 s")

    window = webview.create_window(
        title="Transcriber",
        url=f"http://127.0.0.1:{PORT}",
        width=880,
        height=740,
        min_size=(640, 520),
        background_color="#0f0f0f",
    )

    def _quit():
        window.destroy()

    window.expose(_quit)

    webview.start()
    # webview.start() blocks until the window is destroyed.
    # The daemon server_thread exits automatically with the process.
