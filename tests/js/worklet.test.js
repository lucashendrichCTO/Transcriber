/**
 * Tests for PCMWorklet.process() logic from static/worklet-processor.js.
 *
 * The worklet runs in a browser AudioWorklet context which isn't available in
 * Node. The core logic is extracted verbatim into a plain class here so we can
 * unit test it. After the planned refactor the class can be imported directly.
 */
import { describe, it, expect, vi } from "vitest";

// Extracted core logic from worklet-processor.js
class PCMWorkletCore {
  constructor(postMessage) {
    this._buf = [];
    this._count = 0;
    this._batch = 4096;
    this._post = postMessage;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input.length || !input[0] || !input[0].length) return true;

    const numCh = input.length;
    const frameCount = input[0].length;
    const mono = new Float32Array(frameCount);
    for (let ch = 0; ch < numCh; ch++) {
      for (let i = 0; i < frameCount; i++) mono[i] += input[ch][i];
    }
    for (let i = 0; i < frameCount; i++) mono[i] /= numCh;

    this._buf.push(mono);
    this._count += frameCount;
    if (this._count >= this._batch) {
      const merged = new Float32Array(this._count);
      let offset = 0;
      for (const c of this._buf) { merged.set(c, offset); offset += c.length; }
      this._post(merged);
      this._buf = [];
      this._count = 0;
    }
    return true;
  }
}

function makeFrames(numChannels, frameCount, value = 0) {
  return Array.from({ length: numChannels }, () =>
    new Float32Array(frameCount).fill(value)
  );
}

// ---------------------------------------------------------------------------
// Return value
// ---------------------------------------------------------------------------

describe("return value", () => {
  it("always returns true", () => {
    const post = vi.fn();
    const w = new PCMWorkletCore(post);
    expect(w.process([makeFrames(1, 128)])).toBe(true);
  });

  it("returns true with empty inputs", () => {
    const w = new PCMWorkletCore(vi.fn());
    expect(w.process([[]])).toBe(true);
    expect(w.process([])).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Batching — does not post until _batch (4096) samples accumulated
// ---------------------------------------------------------------------------

describe("batching", () => {
  it("does not post before 4096 samples are accumulated", () => {
    const post = vi.fn();
    const w = new PCMWorkletCore(post);
    // Send 128 samples — well below 4096
    w.process([makeFrames(1, 128, 0.5)]);
    expect(post).not.toHaveBeenCalled();
  });

  it("posts exactly once when >= 4096 samples are reached", () => {
    const post = vi.fn();
    const w = new PCMWorkletCore(post);
    // 32 calls × 128 samples = 4096 — posts on the last call
    for (let i = 0; i < 32; i++) {
      w.process([makeFrames(1, 128, 0.1)]);
    }
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("posted batch is a Float32Array of 4096 samples", () => {
    const post = vi.fn();
    const w = new PCMWorkletCore(post);
    for (let i = 0; i < 32; i++) {
      w.process([makeFrames(1, 128, 0.1)]);
    }
    const batch = post.mock.calls[0][0];
    expect(batch).toBeInstanceOf(Float32Array);
    expect(batch.length).toBe(4096);
  });

  it("resets buffer after posting — next 128 samples do not re-trigger post", () => {
    const post = vi.fn();
    const w = new PCMWorkletCore(post);
    for (let i = 0; i < 32; i++) {
      w.process([makeFrames(1, 128, 0.1)]);
    }
    post.mockClear();
    w.process([makeFrames(1, 128, 0.1)]);
    expect(post).not.toHaveBeenCalled();
  });

  it("posts when a single call delivers exactly 4096 samples", () => {
    const post = vi.fn();
    const w = new PCMWorkletCore(post);
    w.process([makeFrames(1, 4096, 0.5)]);
    expect(post).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// Mono mixdown — channels must be averaged, not just summed
// ---------------------------------------------------------------------------

describe("mono mixdown", () => {
  it("single channel passes through unchanged", () => {
    const post = vi.fn();
    const w = new PCMWorkletCore(post);
    const frames = makeFrames(1, 4096, 0.6);
    w.process([frames]);
    const batch = post.mock.calls[0][0];
    expect(batch[0]).toBeCloseTo(0.6, 5);
  });

  it("two equal channels produce the same value (not doubled)", () => {
    const post = vi.fn();
    const w = new PCMWorkletCore(post);
    // Two channels both at 0.5 → mono average = 0.5 (not 1.0)
    const frames = makeFrames(2, 4096, 0.5);
    w.process([frames]);
    const batch = post.mock.calls[0][0];
    expect(batch[0]).toBeCloseTo(0.5, 5);
  });

  it("two opposite channels average to zero", () => {
    const post = vi.fn();
    const w = new PCMWorkletCore(post);
    const ch0 = new Float32Array(4096).fill(0.4);
    const ch1 = new Float32Array(4096).fill(-0.4);
    w.process([[ch0, ch1]]);
    const batch = post.mock.calls[0][0];
    expect(batch[0]).toBeCloseTo(0.0, 5);
  });

  it("three channels average correctly", () => {
    const post = vi.fn();
    const w = new PCMWorkletCore(post);
    const ch0 = new Float32Array(4096).fill(0.3);
    const ch1 = new Float32Array(4096).fill(0.6);
    const ch2 = new Float32Array(4096).fill(0.9);
    w.process([[ch0, ch1, ch2]]);
    const batch = post.mock.calls[0][0];
    expect(batch[0]).toBeCloseTo(0.6, 5);
  });
});

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

describe("edge cases", () => {
  it("empty inputs[0] array → returns true, no post", () => {
    const post = vi.fn();
    const w = new PCMWorkletCore(post);
    w.process([[]]);
    expect(post).not.toHaveBeenCalled();
  });

  it("null input channel → returns true, no post", () => {
    const post = vi.fn();
    const w = new PCMWorkletCore(post);
    w.process([[null]]);
    expect(post).not.toHaveBeenCalled();
  });

  it("empty inputs array → returns true, no post", () => {
    const post = vi.fn();
    const w = new PCMWorkletCore(post);
    w.process([]);
    expect(post).not.toHaveBeenCalled();
  });
});
