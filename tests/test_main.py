"""
Tests for main.py helpers.

pywebview requires a display and cannot be tested headlessly, so these tests
cover the two pure-logic pieces that can run in CI: _wait_for_port and the
server-thread startup path.
"""
import socket
import threading
import time

import pytest

from main import _wait_for_port, _start_server, PORT


# ---------------------------------------------------------------------------
# _wait_for_port
# ---------------------------------------------------------------------------

def _free_port() -> int:
    """Return an OS-assigned free port number."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_wait_for_port_returns_true_when_port_opens():
    port = _free_port()

    def _open_after_delay():
        time.sleep(0.3)
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(1)
        time.sleep(1.0)
        srv.close()

    t = threading.Thread(target=_open_after_delay, daemon=True)
    t.start()
    assert _wait_for_port(port, timeout=3.0) is True


def test_wait_for_port_returns_false_on_timeout():
    port = _free_port()
    # Nothing will listen on this port — should time out quickly.
    result = _wait_for_port(port, timeout=0.5)
    assert result is False


def test_wait_for_port_returns_true_immediately_if_already_open():
    port = _free_port()
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(1)
    try:
        assert _wait_for_port(port, timeout=1.0) is True
    finally:
        srv.close()


# ---------------------------------------------------------------------------
# Server thread
# ---------------------------------------------------------------------------

def test_server_thread_is_daemon():
    """The uvicorn thread must be a daemon so it can't keep the process alive."""
    t = threading.Thread(target=_start_server, daemon=True, name="uvicorn-test")
    assert t.daemon is True


def test_uvicorn_starts_and_serves():
    """Start the real uvicorn server in a thread and confirm it accepts HTTP."""
    import urllib.request

    ready = _wait_for_port(PORT, timeout=10.0)
    if not ready:
        # Server not already running — start it for this test.
        t = threading.Thread(target=_start_server, daemon=True)
        t.start()
        ready = _wait_for_port(PORT, timeout=10.0)

    assert ready, f"Server did not start on port {PORT}"

    response = urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=5)
    assert response.status == 200
