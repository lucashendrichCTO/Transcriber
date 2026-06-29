// Runs on the audio thread. Buffers Float32 mic samples and posts them to the
// main thread in ~4096-sample batches to keep message traffic reasonable.
class PCMWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buf = [];
    this._count = 0;
    this._batch = 4096;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input.length || !input[0] || !input[0].length) return true;

    // Sum all channels to mono — handles both stereo sources (ch0+ch1) and
    // Aggregate Device streams where mic arrives on ch2 alongside BlackHole on ch0+ch1
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
      this.port.postMessage(merged);
      this._buf = [];
      this._count = 0;
    }
    return true;
  }
}

registerProcessor("pcm-worklet", PCMWorklet);
