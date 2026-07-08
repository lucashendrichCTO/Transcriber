"""
Integration tests for the WebSocket session state machine in app.py.

Uses Starlette's TestClient WebSocket support (synchronous, no real server needed).
The Whisper model is loaded once per session; PCM sent in tests is silence so
transcription returns "" quickly without hallucination.
"""
import json
import os
from pathlib import Path

import numpy as np
import pytest
from starlette.testclient import TestClient

# Force DEBUG_WAV off by default so tests don't write WAV files unless explicitly
# testing that behaviour.  Must be set before importing app.
os.environ.setdefault("DEBUG_WAV", "0")

from app import app  # noqa: E402  (import after env setup)


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _silence_pcm(duration_s: float = 0.5, sample_rate: int = 16000) -> bytes:
    n = int(duration_s * sample_rate)
    return b"\x00\x00" * n


def _recv_json(ws) -> dict:
    return json.loads(ws.receive_text())


# ---------------------------------------------------------------------------
# Basic protocol tests
# ---------------------------------------------------------------------------

def test_websocket_connects(client):
    with client.websocket_connect("/ws") as ws:
        pass  # clean connect + disconnect should not raise


def test_send_pcm_returns_transcript_message(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_bytes(_silence_pcm(0.5))
        msg = _recv_json(ws)
        assert msg["type"] == "transcript"
        assert "text" in msg


def test_transcript_text_is_string(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_bytes(_silence_pcm(0.5))
        msg = _recv_json(ws)
        assert isinstance(msg["text"], str)


def test_silence_pcm_produces_empty_transcript(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_bytes(_silence_pcm(2.0))
        msg = _recv_json(ws)
        assert msg["type"] == "transcript"
        assert msg["text"] == ""


# ---------------------------------------------------------------------------
# SAVE command
# ---------------------------------------------------------------------------

def test_save_returns_saved_message(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_bytes(_silence_pcm(0.5))
        _recv_json(ws)  # discard transcript preview
        ws.send_text("SAVE")
        msg = _recv_json(ws)
        assert msg["type"] == "saved"


def test_save_message_contains_path(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_bytes(_silence_pcm(0.5))
        _recv_json(ws)
        ws.send_text("SAVE")
        msg = _recv_json(ws)
        assert "path" in msg
        assert msg["path"].endswith(".txt")


def test_save_creates_txt_file(client, tmp_path, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "SAVE_DIR", tmp_path)
    with client.websocket_connect("/ws") as ws:
        ws.send_bytes(_silence_pcm(0.5))
        _recv_json(ws)
        ws.send_text("SAVE")
        msg = _recv_json(ws)
    assert Path(msg["path"]).exists()


def test_save_txt_file_is_readable(client, tmp_path, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "SAVE_DIR", tmp_path)
    with client.websocket_connect("/ws") as ws:
        ws.send_bytes(_silence_pcm(0.5))
        _recv_json(ws)
        ws.send_text("SAVE")
        msg = _recv_json(ws)
    content = Path(msg["path"]).read_text(encoding="utf-8")
    assert isinstance(content, str)


def test_save_with_no_audio_still_saves(client, tmp_path, monkeypatch):
    """SAVE immediately after connect (no audio) should write an empty .txt."""
    import app as app_module
    monkeypatch.setattr(app_module, "SAVE_DIR", tmp_path)
    with client.websocket_connect("/ws") as ws:
        ws.send_text("SAVE")
        msg = _recv_json(ws)
    assert msg["type"] == "saved"
    assert Path(msg["path"]).exists()


# ---------------------------------------------------------------------------
# CANCEL command
# ---------------------------------------------------------------------------

def test_cancel_returns_cancelled_message(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_bytes(_silence_pcm(0.5))
        _recv_json(ws)
        ws.send_text("CANCEL")
        msg = _recv_json(ws)
        assert msg["type"] == "cancelled"


# ---------------------------------------------------------------------------
# Session reset — state must not bleed between SAVE calls
# ---------------------------------------------------------------------------

def test_session_resets_after_save(client, tmp_path, monkeypatch):
    """After a SAVE the server clears session state; a second immediate SAVE with
    no new audio must return an empty transcript (no bleed from prior session)."""
    import app as app_module
    monkeypatch.setattr(app_module, "SAVE_DIR", tmp_path)
    with client.websocket_connect("/ws") as ws:
        ws.send_bytes(_silence_pcm(0.5))
        _recv_json(ws)
        ws.send_text("SAVE")
        first = _recv_json(ws)

        # Second save with no audio — session must be clean
        ws.send_text("SAVE")
        second = _recv_json(ws)

    assert first["type"] == "saved"
    assert second["type"] == "saved"
    # The key invariant: no PCM or segments bleed into the next session
    assert second["text"] == ""


def test_session_resets_after_cancel(client, tmp_path, monkeypatch):
    """After CANCEL, a SAVE should save an empty file (no leftover PCM)."""
    import app as app_module
    monkeypatch.setattr(app_module, "SAVE_DIR", tmp_path)
    with client.websocket_connect("/ws") as ws:
        ws.send_bytes(_silence_pcm(0.5))
        _recv_json(ws)
        ws.send_text("CANCEL")
        _recv_json(ws)

        ws.send_text("SAVE")
        msg = _recv_json(ws)

    assert msg["type"] == "saved"
    assert msg["text"] == ""


# ---------------------------------------------------------------------------
# WAV file behaviour controlled by per-session config message
# ---------------------------------------------------------------------------

def test_save_wav_false_writes_no_wav(client, tmp_path, monkeypatch):
    """When the client sends save_wav=false (the default), no WAV is written."""
    import app as app_module
    monkeypatch.setattr(app_module, "SAVE_DIR", tmp_path)
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "config", "save_wav": False}))
        ws.send_bytes(_silence_pcm(0.5))
        _recv_json(ws)
        ws.send_text("SAVE")
        _recv_json(ws)
    assert len(list(tmp_path.glob("*.wav"))) == 0


def test_save_wav_true_writes_wav(client, tmp_path, monkeypatch):
    """When the client sends save_wav=true, a WAV file is written on SAVE."""
    import app as app_module
    monkeypatch.setattr(app_module, "SAVE_DIR", tmp_path)
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "config", "save_wav": True}))
        ws.send_bytes(_silence_pcm(0.5))
        _recv_json(ws)
        ws.send_text("SAVE")
        _recv_json(ws)
    assert len(list(tmp_path.glob("*.wav"))) == 1


def test_save_wav_without_config_writes_no_wav(client, tmp_path, monkeypatch):
    """No config message sent → default save_wav=False → no WAV written."""
    import app as app_module
    monkeypatch.setattr(app_module, "SAVE_DIR", tmp_path)
    with client.websocket_connect("/ws") as ws:
        ws.send_bytes(_silence_pcm(0.5))
        _recv_json(ws)
        ws.send_text("SAVE")
        _recv_json(ws)
    assert len(list(tmp_path.glob("*.wav"))) == 0


# ---------------------------------------------------------------------------
# /devices endpoint
# ---------------------------------------------------------------------------

def test_devices_endpoint_returns_json(client):
    resp = client.get("/devices")
    assert resp.status_code == 200
    data = resp.json()
    assert "devices" in data
    assert isinstance(data["devices"], list)


def test_devices_endpoint_items_have_required_keys(client):
    """Each device entry must have deviceId, label, and kind."""
    resp = client.get("/devices")
    for d in resp.json().get("devices", []):
        assert "deviceId" in d
        assert "label" in d
        assert d.get("kind") == "audioinput"


def test_devices_endpoint_returns_empty_list_when_sounddevice_fails(client, monkeypatch):
    """If sounddevice raises, /devices returns an empty list rather than 500."""
    import sys
    import types

    # Inject a broken sounddevice module
    fake = types.ModuleType("sounddevice")
    def _boom(*a, **kw): raise RuntimeError("no audio hw")
    fake.query_devices = _boom
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    resp = client.get("/devices")
    assert resp.status_code == 200
    assert resp.json()["devices"] == []


# ---------------------------------------------------------------------------
# Python-capture mode (JSON start command)
# ---------------------------------------------------------------------------

class _FakeInputStream:
    """No-op sounddevice.InputStream — never fires the callback."""
    def __init__(self, **kwargs):
        pass
    def start(self): pass
    def stop(self): pass
    def close(self): pass


def test_python_start_then_save_returns_saved(client, tmp_path, monkeypatch):
    """start JSON + SAVE must always return 'saved', even with no audio."""
    import sys, types, app as app_module
    monkeypatch.setattr(app_module, "SAVE_DIR", tmp_path)

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.InputStream = _FakeInputStream
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "config", "save_wav": False}))
        ws.send_text(json.dumps({"type": "start", "meeting_device": "", "mic_device": ""}))
        ws.send_text("SAVE")
        msg = _recv_json(ws)

    assert msg["type"] == "saved"
    assert Path(msg["path"]).exists()


def test_python_start_produces_audio_from_callback(client, tmp_path, monkeypatch):
    """When the InputStream callback fires with PCM data it reaches pending_pcm."""
    import sys, types, threading, time, numpy as np, app as app_module
    monkeypatch.setattr(app_module, "SAVE_DIR", tmp_path)

    callbacks: list = []

    class _CallbackCapture:
        def __init__(self, **kwargs):
            callbacks.append(kwargs.get("callback"))
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.InputStream = _CallbackCapture
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "config", "save_wav": False}))
        ws.send_text(json.dumps({"type": "start", "meeting_device": "", "mic_device": ""}))

        # Let the capture task spin up, then fire the callback from a thread
        time.sleep(0.3)
        if callbacks:
            audio = np.ones((4096, 1), dtype=np.float32) * 0.1
            callbacks[0](audio, 4096, None, None)
            time.sleep(0.2)

        ws.send_text("SAVE")
        msg = _recv_json(ws)

    assert msg["type"] == "saved"


def test_python_capture_drops_stalled_stream_instead_of_blocking(client, tmp_path, monkeypatch):
    """Regression test: if one stream (e.g. a flaky Bluetooth mic) never produces
    a callback while the other (e.g. BlackHole) is actively delivering audio, the
    healthy stream must not be blocked forever. Before the fix, mixing required
    ALL configured streams to advance (min() over accumulator sizes), so a single
    dead stream meant total silence even though the other device worked fine."""
    import sys, types, time, numpy as np, app as app_module
    monkeypatch.setattr(app_module, "SAVE_DIR", tmp_path)

    callbacks: list = []

    class _CallbackCapture:
        def __init__(self, **kwargs):
            callbacks.append(kwargs.get("callback"))
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.InputStream = _CallbackCapture
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "config", "save_wav": False}))
        ws.send_text(json.dumps({"type": "start", "meeting_device": "0", "mic_device": "1"}))
        time.sleep(0.3)
        assert len(callbacks) == 2  # meeting=callbacks[0], mic=callbacks[1]

        # Only the meeting-audio stream ever fires; the mic stream is stalled.
        audio = np.ones((4096, 1), dtype=np.float32) * 0.1
        deadline = time.time() + 2.0
        while time.time() < deadline:
            callbacks[0](audio, 4096, None, None)
            time.sleep(0.1)

        ws.send_text("SAVE")
        messages = []
        while True:
            msg = _recv_json(ws)
            messages.append(msg)
            if msg["type"] == "saved":
                break

    assert not any(m["type"] == "error" for m in messages)
    warnings = [m for m in messages if m["type"] == "warning"]
    assert warnings, "expected a non-fatal warning about the stalled microphone stream"
    assert "microphone" in warnings[0]["text"]
    # The meeting-audio stream's data must have reached pending_pcm despite the
    # stalled mic stream — i.e. actual (non-empty-buffer) capture happened.
    assert messages[-1]["type"] == "saved"


def test_python_capture_silence_sends_warning_not_error(client, tmp_path, monkeypatch):
    """Regression test: the 'no audio yet' diagnostic must be a non-fatal warning,
    never an 'error' — an 'error' message makes the frontend disable Stop & Save,
    effectively ending the session even though capture is still running fine."""
    import sys, types, time, numpy as np, app as app_module
    monkeypatch.setattr(app_module, "SAVE_DIR", tmp_path)

    callbacks: list = []

    class _CallbackCapture:
        def __init__(self, **kwargs):
            callbacks.append(kwargs.get("callback"))
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.InputStream = _CallbackCapture
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "config", "save_wav": False}))
        # Single stream (meeting-audio only, no mic) — mirrors "record a webinar,
        # I'm not speaking" usage where mic_device is intentionally empty.
        ws.send_text(json.dumps({"type": "start", "meeting_device": "0", "mic_device": ""}))
        time.sleep(0.3)
        assert len(callbacks) == 1

        silence = np.zeros((4096, 1), dtype=np.float32)
        deadline = time.time() + 5.5
        while time.time() < deadline:
            callbacks[0](silence, 4096, None, None)
            time.sleep(0.1)

        ws.send_text("SAVE")
        messages = []
        while True:
            msg = _recv_json(ws)
            messages.append(msg)
            if msg["type"] == "saved":
                break

    assert not any(m["type"] == "error" for m in messages)
    assert any(m["type"] == "warning" for m in messages)
    assert messages[-1]["type"] == "saved"


def test_python_start_cancel_resets_session(client, tmp_path, monkeypatch):
    """CANCEL after start should return 'cancelled' and clear the session."""
    import sys, types, app as app_module
    monkeypatch.setattr(app_module, "SAVE_DIR", tmp_path)

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.InputStream = _FakeInputStream
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "start", "meeting_device": "", "mic_device": ""}))
        ws.send_text("CANCEL")
        msg = _recv_json(ws)

    assert msg["type"] == "cancelled"


# ---------------------------------------------------------------------------
# Independent connections are isolated
# ---------------------------------------------------------------------------

def test_two_connections_are_independent(client, tmp_path, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "SAVE_DIR", tmp_path)
    # Open and save on connection 1, then open connection 2 and verify it
    # starts with a clean slate (its SAVE produces an empty transcript).
    with client.websocket_connect("/ws") as ws1:
        ws1.send_bytes(_silence_pcm(0.5))
        _recv_json(ws1)
        ws1.send_text("SAVE")
        _recv_json(ws1)

    with client.websocket_connect("/ws") as ws2:
        ws2.send_text("SAVE")
        msg = _recv_json(ws2)

    assert msg["type"] == "saved"
    assert msg["text"] == ""
