"""
Unit tests for transcriber.transcribe_pcm().

The Whisper model is loaded once per test session via a session-scoped fixture
to avoid the ~2s startup cost on every test.
"""
import math

import numpy as np
import pytest

from transcriber import get_model, transcribe_pcm


@pytest.fixture(scope="session", autouse=True)
def preload_model():
    """Load the Whisper model once for the whole test session."""
    get_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sine_pcm(freq_hz: float = 440.0, duration_s: float = 2.0, sample_rate: int = 16000) -> bytes:
    """Return raw 16-bit signed LE mono PCM for a pure sine tone."""
    n = int(duration_s * sample_rate)
    t = np.linspace(0, duration_s, n, endpoint=False)
    wave = (np.sin(2 * math.pi * freq_hz * t) * 0.5 * 32767).astype(np.int16)
    return wave.tobytes()


def _silence_pcm(duration_s: float = 1.0, sample_rate: int = 16000) -> bytes:
    n = int(duration_s * sample_rate)
    return b"\x00\x00" * n


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_empty_bytes_returns_empty_string():
    assert transcribe_pcm(b"") == ""


def test_silence_returns_empty_string():
    pcm = _silence_pcm(duration_s=2.0)
    result = transcribe_pcm(pcm)
    assert result == ""


def test_non_silent_audio_returns_something():
    """A 440 Hz tone is not speech, but it is non-silent — Whisper may hallucinate
    some text. The important contract is that it does NOT crash and returns a str."""
    pcm = _sine_pcm(duration_s=3.0)
    result = transcribe_pcm(pcm)
    assert isinstance(result, str)


def test_skip_secs_excludes_early_segments():
    """skip_secs=999 should exclude every segment, returning an empty string."""
    pcm = _sine_pcm(duration_s=3.0)
    result = transcribe_pcm(pcm, skip_secs=999.0)
    assert result == ""


def test_skip_secs_zero_keeps_all_segments():
    """skip_secs=0 (default) should behave identically to no skip_secs."""
    pcm = _sine_pcm(duration_s=3.0)
    assert transcribe_pcm(pcm, skip_secs=0.0) == transcribe_pcm(pcm)


def test_return_type_is_always_str():
    for pcm in [b"", _silence_pcm(), _sine_pcm()]:
        result = transcribe_pcm(pcm)
        assert isinstance(result, str), f"Expected str, got {type(result)}"


def test_custom_sample_rate_accepted():
    """transcribe_pcm accepts a sample_rate argument without raising."""
    pcm = _silence_pcm(duration_s=1.0, sample_rate=16000)
    result = transcribe_pcm(pcm, sample_rate=16000)
    assert isinstance(result, str)
