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
    """Return audio input devices as [{deviceId, label, kind}], or [] on failure.

    deviceId is the device's NAME, not its numeric PortAudio index. Indices are
    NOT stable — a Bluetooth device (AirPods, Beats, etc.) connecting or
    disconnecting re-numbers every subsequent device in sd.query_devices().
    Caching an index from when this list was fetched (e.g. in a browser
    dropdown) and using it later to open a stream can silently open the WRONG
    device once the index has drifted — a real bug that made BlackHole capture
    fail intermittently. Opening by name and re-resolving the current index at
    open time (see open_input_stream/_resolve_device_index) avoids that.
    """
    try:
        import sounddevice as sd
    except Exception:
        return []
    try:
        devices = []
        for d in sd.query_devices():
            if d["max_input_channels"] > 0:
                devices.append({
                    "deviceId": d["name"],
                    "label": d["name"],
                    "kind": "audioinput",
                })
        return devices
    except Exception:
        return []


def _resolve_device_index(name: str):
    """Look up the CURRENT PortAudio index for an input device by name.

    Re-queries sd.query_devices() fresh (rather than trusting a cached index)
    so a device that has shifted position since it was listed is still found
    correctly. Falls back to treating `name` as a raw index for callers still
    passing a numeric string (also keeps unit tests that mock sounddevice
    without query_devices() working, since that lookup then just no-ops).
    """
    import sounddevice as sd

    try:
        devices = sd.query_devices()
    except Exception:
        devices = []
    for i, d in enumerate(devices):
        if d.get("name") == name and d.get("max_input_channels", 0) > 0:
            return i
    try:
        return int(name)
    except (TypeError, ValueError):
        raise ValueError(f"input device {name!r} not found")


def open_input_stream(device, callback, blocksize: int = 4096):
    """Open (but do not start) a 16 kHz mono float32 InputStream.

    `device` is a device NAME as returned by list_input_devices (resolved to
    its current numeric index here, not a cached one — see
    _resolve_device_index for why). `callback` receives
    (indata, frames, time_info, status) on the audio thread. Raises if
    sounddevice is unavailable, the named device can't be found, or the
    device cannot be opened.
    """
    import sounddevice as sd

    dev = _resolve_device_index(device) if device not in (None, "") else None
    return sd.InputStream(
        device=dev,
        channels=1,
        samplerate=TARGET_RATE,
        dtype="float32",
        callback=callback,
        blocksize=blocksize,
    )
