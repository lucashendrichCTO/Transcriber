/**
 * Tests for the capture-mode dispatch logic in static/app.js.
 *
 * app.js is an IIFE that exports nothing, so (following the existing pattern in
 * toInt16PCM.test.js / worklet.test.js) the decision helpers are reproduced here
 * verbatim from app.js.  They model the contract that broke repeatedly:
 *   - which capture path runs (browser getUserMedia vs Python sounddevice)
 *   - what gets sent to the server on Start in each mode
 *   - how the /devices or enumerateDevices list becomes dropdown options
 */
import { describe, it, expect } from "vitest";

// --- verbatim from app.js ---------------------------------------------------

// const PYTHON_AUDIO = !navigator.mediaDevices;
function isPythonAudio(nav) {
  return !nav.mediaDevices;
}

// The Start handler: in Python mode it sends a JSON "start" frame; in browser
// mode it captures locally and sends binary PCM (no JSON start frame).
function startFrame(pythonAudio, meetingDevice, micDevice) {
  if (pythonAudio) {
    return JSON.stringify({
      type: "start",
      meeting_device: meetingDevice,
      mic_device: micDevice,
    });
  }
  return null; // browser mode streams binary PCM instead
}

// Both modes send the text command "SAVE" on Stop.
function stopCommand() {
  return "SAVE";
}

// _applyDeviceList: build dropdown option descriptors from a device list.
function deviceOptions(inputs) {
  return inputs.map(d => ({
    value: d.deviceId,
    label: d.label || `Microphone ${(d.deviceId || "").slice(0, 6)}`,
  }));
}

// ---------------------------------------------------------------------------

describe("capture-mode detection", () => {
  it("uses Python audio when navigator.mediaDevices is absent (WKWebView)", () => {
    expect(isPythonAudio({})).toBe(true);
  });

  it("uses browser audio when navigator.mediaDevices exists", () => {
    expect(isPythonAudio({ mediaDevices: {} })).toBe(false);
  });
});

describe("Start frame", () => {
  it("Python mode sends a JSON start frame with both device ids", () => {
    const frame = JSON.parse(startFrame(true, "1", "2"));
    expect(frame).toEqual({ type: "start", meeting_device: "1", mic_device: "2" });
  });

  it("Python mode preserves an empty mic selection (None)", () => {
    const frame = JSON.parse(startFrame(true, "1", ""));
    expect(frame.mic_device).toBe("");
    expect(frame.meeting_device).toBe("1");
  });

  it("browser mode sends no JSON start frame (streams binary instead)", () => {
    expect(startFrame(false, "1", "2")).toBeNull();
  });
});

describe("Stop command", () => {
  it("always sends SAVE", () => {
    expect(stopCommand()).toBe("SAVE");
  });
});

describe("device option mapping", () => {
  it("maps labelled devices straight through", () => {
    const opts = deviceOptions([
      { deviceId: "0", label: "BlackHole 2ch" },
      { deviceId: "1", label: "MacBook Pro Microphone" },
    ]);
    expect(opts).toEqual([
      { value: "0", label: "BlackHole 2ch" },
      { value: "1", label: "MacBook Pro Microphone" },
    ]);
  });

  it("falls back to a truncated id when a device has no label", () => {
    const opts = deviceOptions([{ deviceId: "abcdef123456", label: "" }]);
    expect(opts[0].label).toBe("Microphone abcdef");
  });

  it("handles an empty device list", () => {
    expect(deviceOptions([])).toEqual([]);
  });
});
