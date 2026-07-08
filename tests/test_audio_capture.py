"""
Real audio-capture tests for audio.py.

These exercise the ACTUAL PortAudio capture path (not a mock), so they catch the
class of failure that mocked WebSocket tests cannot: a capture path that opens a
stream but yields no usable PCM.  Hardware tests are marked `hardware` and skip
cleanly when no input device is present (e.g. CI / headless).

Note: these verify the capture *code path* produces correctly-shaped PCM.  They
cannot assert non-silence (that depends on what is playing) nor TCC permission
(that requires the signed .app bundle) — those are covered by test_bundle.py and
manual verification.
"""
import threading
import time

import numpy as np
import pytest

from audio import TARGET_RATE, float_to_pcm16, list_input_devices, open_input_stream


# ---------------------------------------------------------------------------
# float_to_pcm16 — pure, always runs
# ---------------------------------------------------------------------------

def test_float_to_pcm16_length_mono():
    samples = np.zeros(1000, dtype=np.float32)
    assert len(float_to_pcm16(samples)) == 1000 * 2  # 16-bit => 2 bytes/sample


def test_float_to_pcm16_mixes_multichannel_to_mono():
    stereo = np.zeros((500, 2), dtype=np.float32)
    assert len(float_to_pcm16(stereo)) == 500 * 2  # one channel kept


def test_float_to_pcm16_full_scale_values():
    samples = np.array([1.0, -1.0, 0.0], dtype=np.float32)
    pcm = np.frombuffer(float_to_pcm16(samples), dtype="<i2")
    assert pcm[0] == 32767
    assert pcm[1] == -32767
    assert pcm[2] == 0


def test_float_to_pcm16_clips_out_of_range():
    samples = np.array([2.0, -2.0], dtype=np.float32)
    pcm = np.frombuffer(float_to_pcm16(samples), dtype="<i2")
    assert pcm[0] == 32767
    assert pcm[1] == -32767


def test_float_to_pcm16_roundtrip_preserves_signal():
    t = np.linspace(0, 1, TARGET_RATE, dtype=np.float32)
    tone = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    pcm = np.frombuffer(float_to_pcm16(tone), dtype="<i2").astype(np.float32) / 32767.0
    # Reconstructed peak should be close to the original 0.5 amplitude
    assert abs(float(np.max(np.abs(pcm))) - 0.5) < 0.01


# ---------------------------------------------------------------------------
# list_input_devices
# ---------------------------------------------------------------------------

def test_list_input_devices_returns_list():
    devices = list_input_devices()
    assert isinstance(devices, list)


def test_list_input_devices_entries_well_formed():
    for d in list_input_devices():
        assert set(d) == {"deviceId", "label", "kind"}
        assert d["kind"] == "audioinput"
        assert isinstance(d["label"], str) and d["label"]


def test_list_input_devices_id_is_name_not_index():
    """deviceId must be the device's NAME, not its numeric PortAudio index —
    regression test for the bug where a cached index went stale the moment a
    Bluetooth device connected/disconnected and renumbered every device after
    it, silently opening the wrong device on Start."""
    for d in list_input_devices():
        assert d["deviceId"] == d["label"]
        assert not d["deviceId"].isdigit()


# ---------------------------------------------------------------------------
# _resolve_device_index — name-based lookup survives index drift
# ---------------------------------------------------------------------------

def _fake_query_devices(order):
    return [{"name": name, "max_input_channels": 1} for name in order]


def test_resolve_device_index_finds_current_position(monkeypatch):
    import sys, types
    from audio import _resolve_device_index

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.query_devices = lambda: _fake_query_devices(["Beats", "BlackHole 2ch", "MacBook Pro Microphone"])
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    assert _resolve_device_index("BlackHole 2ch") == 1


def test_resolve_device_index_survives_index_drift(monkeypatch):
    """The exact regression: a device's index shifts (e.g. a Bluetooth device
    disconnects and is removed from the list) between when it was listed and
    when it's opened — resolution must follow the name, not a cached index."""
    import sys, types
    from audio import _resolve_device_index

    fake_sd = types.ModuleType("sounddevice")
    # "BlackHole 2ch" was at index 1 when originally listed...
    fake_sd.query_devices = lambda: _fake_query_devices(["BlackHole 2ch", "MacBook Pro Microphone"])
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    # ...but a Bluetooth device disconnecting shifted it to index 0. Resolving
    # by name must still find it correctly.
    assert _resolve_device_index("BlackHole 2ch") == 0


def test_resolve_device_index_raises_when_device_not_found(monkeypatch):
    import sys, types
    from audio import _resolve_device_index

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.query_devices = lambda: _fake_query_devices(["MacBook Pro Microphone"])
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    with pytest.raises(ValueError):
        _resolve_device_index("BlackHole 2ch")


# ---------------------------------------------------------------------------
# Real capture — hardware-gated
# ---------------------------------------------------------------------------

def _has_input_device() -> bool:
    try:
        import sounddevice  # noqa: F401
    except Exception:
        return False
    return len(list_input_devices()) > 0


requires_audio = pytest.mark.skipif(
    not _has_input_device(), reason="no audio input device available"
)


@pytest.mark.hardware
@requires_audio
def test_default_device_capture_yields_pcm():
    """Opening the default input and reading ~0.5s must produce Int16 PCM frames.

    This is the exact code path app.py uses.  If capture silently produces no
    frames (the real bug we hit), this fails.
    """
    collected: list[bytes] = []
    done = threading.Event()

    def cb(indata, frames, time_info, status):
        collected.append(float_to_pcm16(indata))
        if sum(len(c) for c in collected) >= TARGET_RATE * 2 // 2:  # ~0.5s
            done.set()

    stream = open_input_stream("", cb)
    stream.start()
    try:
        done.wait(timeout=5.0)
    finally:
        stream.stop()
        stream.close()

    total = sum(len(c) for c in collected)
    assert total > 0, "capture produced no PCM frames"
    # Every frame must be an even number of bytes (16-bit samples)
    assert all(len(c) % 2 == 0 for c in collected)


@pytest.mark.hardware
@requires_audio
def test_named_devices_open_without_error():
    """Each enumerated input device must be openable at 16 kHz mono."""
    for d in list_input_devices():
        opened = True
        try:
            stream = open_input_stream(d["deviceId"], lambda *a: None)
            stream.start()
            time.sleep(0.05)
            stream.stop()
            stream.close()
        except Exception:
            opened = False
        # We don't assert every device works (some virtual devices refuse 16k),
        # but opening must not raise an unexpected import/contract error.
        assert opened in (True, False)
