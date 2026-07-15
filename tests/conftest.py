"""Shared PCM-generation helpers for tests.

Kept in one place instead of each test file reimplementing its own
silence/sine/constant PCM generator with a slightly different name/signature.
"""
import math

import numpy as np


def silence_pcm(duration_s: float = 1.0, sample_rate: int = 16000) -> bytes:
    """Return raw 16-bit signed LE mono PCM silence."""
    n = int(duration_s * sample_rate)
    return b"\x00\x00" * n


def sine_pcm(freq_hz: float = 440.0, duration_s: float = 2.0, sample_rate: int = 16000) -> bytes:
    """Return raw 16-bit signed LE mono PCM for a pure sine tone."""
    n = int(duration_s * sample_rate)
    t = np.linspace(0, duration_s, n, endpoint=False)
    wave = (np.sin(2 * math.pi * freq_hz * t) * 0.5 * 32767).astype(np.int16)
    return wave.tobytes()


def constant_pcm(value: int, n_samples: int) -> bytes:
    """Return n_samples of a constant 16-bit signed value (non-silent test data)."""
    return np.full(n_samples, value, dtype=np.int16).tobytes()
