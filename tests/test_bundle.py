"""
Bundle integrity tests for Transcriber.app.

These assert the properties that make macOS TCC attribute microphone (and
BlackHole) access to the app — the exact thing that was broken when the bundle
shelled out to Apple's shared python interpreter.

A built bundle is required; tests skip cleanly if none is found.  Run:
    ./make_app.sh
then:
    pytest tests/test_bundle.py -v
"""
from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

import pytest

_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "dist" / "Transcriber.app",
    Path(__file__).resolve().parent.parent / "Transcriber.app",
    Path("/Applications/Transcriber.app"),
]


def _find_bundle() -> Path | None:
    for p in _CANDIDATES:
        if p.exists():
            return p
    return None


BUNDLE = _find_bundle()
requires_bundle = pytest.mark.skipif(
    BUNDLE is None, reason="no built Transcriber.app found (run ./make_app.sh)"
)


@pytest.mark.bundle
@requires_bundle
def test_bundle_has_main_executable():
    exe = BUNDLE / "Contents" / "MacOS" / "Transcriber"
    assert exe.exists(), "bundle main executable missing"


@pytest.mark.bundle
@requires_bundle
def test_main_executable_is_real_binary_not_shell_wrapper():
    """Root-cause guard: the main executable must be a real Mach-O binary, NOT a
    shell script that execs a shared python interpreter.  A shell wrapper makes
    TCC attribute audio access to /usr/.../python3 instead of Transcriber.app,
    so the mic prompt never fires and the app never appears in System Settings."""
    exe = BUNDLE / "Contents" / "MacOS" / "Transcriber"
    kind = subprocess.run(["file", str(exe)], capture_output=True, text=True).stdout
    assert "Mach-O" in kind, f"main executable is not a Mach-O binary: {kind.strip()}"
    assert "shell script" not in kind.lower(), f"main executable is a shell script: {kind.strip()}"


@pytest.mark.bundle
@requires_bundle
def test_no_symlink_to_system_python_in_macos_dir():
    """No component the launcher runs may be a symlink to the system/CLT python."""
    exe = BUNDLE / "Contents" / "MacOS" / "Transcriber"
    if exe.is_symlink():
        target = str(exe.resolve())
        assert "CommandLineTools" not in target and "/usr/bin/python" not in target


@pytest.mark.bundle
@requires_bundle
def test_info_plist_has_microphone_usage_description():
    plist = BUNDLE / "Contents" / "Info.plist"
    data = plistlib.loads(plist.read_bytes())
    assert data.get("NSMicrophoneUsageDescription"), \
        "Info.plist missing NSMicrophoneUsageDescription — TCC cannot prompt"


@pytest.mark.bundle
@requires_bundle
def test_bundle_codesign_verifies():
    result = subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(BUNDLE)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"codesign verification failed: {result.stderr}"


@pytest.mark.bundle
@requires_bundle
def test_bundle_has_audio_input_entitlement():
    """The signed binary must carry the audio-input entitlement so a hardened
    runtime build can access the microphone."""
    exe = BUNDLE / "Contents" / "MacOS" / "Transcriber"
    result = subprocess.run(
        ["codesign", "-d", "--entitlements", ":-", str(exe)],
        capture_output=True, text=True,
    )
    combined = result.stdout + result.stderr
    assert "com.apple.security.device.audio-input" in combined, \
        f"audio-input entitlement not found in signature:\n{combined}"
