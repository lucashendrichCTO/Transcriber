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
