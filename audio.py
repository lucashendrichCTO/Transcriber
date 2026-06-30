"""
audio.py — audio device enumeration and capture via PortAudio (sounddevice).

Used by the desktop (pywebview) build, where audio is captured in Python rather
than in the browser.  Kept in its own module so the capture path is unit- and
hardware-testable independently of the WebSocket handler in app.py.

PCM contract (matches the browser path): 16-bit signed little-endian, mono, 16 kHz.
"""
from __future__ import annotations

import numpy as np

TARGET_RATE = 16000


def float_to_pcm16(samples: np.ndarray) -> bytes:
    """Convert a float32 array in [-1, 1] to 16-bit little-endian PCM bytes.

    Accepts either a 1-D array or a 2-D (frames, channels) array; multi-channel
    input is mixed down to mono by taking the first channel.
    """
    if samples.ndim > 1:
        samples = samples[:, 0]
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


def list_input_devices() -> list[dict]:
    """Return audio input devices as [{deviceId, label, kind}], or [] on failure."""
    try:
        import sounddevice as sd
    except Exception:
        return []
    try:
        devices = []
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                devices.append({
                    "deviceId": str(i),
                    "label": d["name"],
                    "kind": "audioinput",
                })
        return devices
    except Exception:
        return []


def open_input_stream(device, callback, blocksize: int = 4096):
    """Open (but do not start) a 16 kHz mono float32 InputStream.

    `callback` receives (indata, frames, time_info, status) on the audio thread.
    Raises if sounddevice is unavailable or the device cannot be opened.
    """
    import sounddevice as sd

    dev = int(device) if device not in (None, "") else None
    return sd.InputStream(
        device=dev,
        channels=1,
        samplerate=TARGET_RATE,
        dtype="float32",
        callback=callback,
        blocksize=blocksize,
    )
