"""
Unit tests for app._write_wav().

Tests the WAV-writing helper in isolation — no WebSocket or Whisper needed.
"""
import wave
from pathlib import Path

import pytest

from app import _write_wav
from tests.conftest import constant_pcm, silence_pcm


@pytest.fixture
def tmp_wav(tmp_path) -> Path:
    return tmp_path / "test.wav"


def _pcm_bytes(n_samples: int = 16000) -> bytes:
    """Return n_samples of 16-bit signed silence (16kHz assumed)."""
    return silence_pcm(duration_s=n_samples / 16000, sample_rate=16000)


def _pcm_bytes_nonzero(n_samples: int = 16000) -> bytes:
    return constant_pcm(1000, n_samples)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_writes_file(tmp_wav):
    _write_wav(_pcm_bytes(), tmp_wav)
    assert tmp_wav.exists()


def test_wav_has_correct_channels(tmp_wav):
    _write_wav(_pcm_bytes(), tmp_wav)
    with wave.open(str(tmp_wav), "rb") as wf:
        assert wf.getnchannels() == 1


def test_wav_has_correct_sample_width(tmp_wav):
    _write_wav(_pcm_bytes(), tmp_wav)
    with wave.open(str(tmp_wav), "rb") as wf:
        assert wf.getsampwidth() == 2  # 16-bit


def test_wav_has_correct_frame_rate(tmp_wav):
    _write_wav(_pcm_bytes(), tmp_wav)
    with wave.open(str(tmp_wav), "rb") as wf:
        assert wf.getframerate() == 16000


def test_wav_frame_count_matches_input(tmp_wav):
    n = 16000
    _write_wav(_pcm_bytes(n), tmp_wav)
    with wave.open(str(tmp_wav), "rb") as wf:
        assert wf.getnframes() == n


def test_wav_data_round_trips(tmp_wav):
    """Bytes written must be identical when read back."""
    pcm = _pcm_bytes_nonzero(8000)
    _write_wav(pcm, tmp_wav)
    with wave.open(str(tmp_wav), "rb") as wf:
        read_back = wf.readframes(wf.getnframes())
    assert read_back == pcm


def test_empty_pcm_writes_valid_wav(tmp_wav):
    _write_wav(b"", tmp_wav)
    with wave.open(str(tmp_wav), "rb") as wf:
        assert wf.getnframes() == 0
