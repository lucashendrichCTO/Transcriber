/**
 * Tests for the toInt16PCM downsampler from static/app.js.
 *
 * The function is inlined here verbatim from app.js so it can be imported
 * as an ES module. After the planned refactor extracts it to a shared module,
 * this import can be replaced with the real source.
 */
import { describe, it, expect } from "vitest";

const TARGET_RATE = 16000;

function toInt16PCM(float32, inRate) {
  const ratio = inRate / TARGET_RATE;
  const outLen = Math.floor(float32.length / ratio);
  const out = new Int16Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(Math.floor((i + 1) * ratio), float32.length);
    let sum = 0, count = 0;
    for (let j = start; j < end; j++) { sum += float32[j]; count++; }
    let s = count ? sum / count : 0;
    s = Math.max(-1, Math.min(1, s));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Output length
// ---------------------------------------------------------------------------

describe("output length", () => {
  it("48 kHz at ratio 3:1 gives floor(length/3) samples", () => {
    const input = new Float32Array(48000);
    const result = toInt16PCM(input, 48000);
    expect(result.length).toBe(Math.floor(48000 / 3));
  });

  it("44100 Hz gives correct output length", () => {
    const input = new Float32Array(44100);
    const result = toInt16PCM(input, 44100);
    expect(result.length).toBe(Math.floor(44100 / (44100 / 16000)));
  });

  it("same-rate (16 kHz) passes through at equal length", () => {
    const input = new Float32Array(1600);
    const result = toInt16PCM(input, 16000);
    expect(result.length).toBe(1600);
  });

  it("empty input produces empty output", () => {
    const result = toInt16PCM(new Float32Array(0), 48000);
    expect(result.length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Value encoding
// ---------------------------------------------------------------------------

describe("value encoding", () => {
  it("silence (all zeros) produces all-zero Int16 output", () => {
    const input = new Float32Array(48000); // zeros by default
    const result = toInt16PCM(input, 48000);
    expect(result.every(v => v === 0)).toBe(true);
  });

  it("maximum positive value 1.0 encodes to 0x7fff (32767)", () => {
    const input = new Float32Array([1.0]);
    const result = toInt16PCM(input, TARGET_RATE);
    expect(result[0]).toBe(0x7fff);
  });

  it("maximum negative value -1.0 encodes to -0x8000 (-32768)", () => {
    const input = new Float32Array([-1.0]);
    const result = toInt16PCM(input, TARGET_RATE);
    expect(result[0]).toBe(-0x8000);
  });

  it("value > 1.0 is clamped to 0x7fff (no overflow wrapping)", () => {
    const input = new Float32Array([2.0]);
    const result = toInt16PCM(input, TARGET_RATE);
    expect(result[0]).toBe(0x7fff);
  });

  it("value < -1.0 is clamped to -0x8000", () => {
    const input = new Float32Array([-2.0]);
    const result = toInt16PCM(input, TARGET_RATE);
    expect(result[0]).toBe(-0x8000);
  });

  it("0.5 encodes to approximately 0x3fff (half positive range)", () => {
    const input = new Float32Array([0.5]);
    const result = toInt16PCM(input, TARGET_RATE);
    // 0.5 * 0x7fff = 16383.5 → truncated to 16383
    expect(result[0]).toBe(Math.floor(0.5 * 0x7fff));
  });
});

// ---------------------------------------------------------------------------
// Averaging window
// ---------------------------------------------------------------------------

describe("averaging window", () => {
  it("two equal samples at 32 kHz average to single sample at 16 kHz", () => {
    // ratio = 2, so two input samples map to one output
    const val = 0.4;
    const input = new Float32Array([val, val]);
    const result = toInt16PCM(input, 32000);
    expect(result.length).toBe(1);
    // average of [val, val] = val → Math.floor(val * 0x7fff)
    expect(result[0]).toBe(Math.floor(val * 0x7fff));
  });

  it("two opposite samples at 32 kHz average to ~zero", () => {
    const input = new Float32Array([0.5, -0.5]);
    const result = toInt16PCM(input, 32000);
    expect(result[0]).toBe(0);
  });
});
