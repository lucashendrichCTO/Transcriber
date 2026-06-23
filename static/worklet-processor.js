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
    if (input && input[0] && input[0].length) {
      // Copy — the render-quantum buffer is reused each call
      this._buf.push(new Float32Array(input[0]));
      this._count += input[0].length;
      if (this._count >= this._batch) {
        const merged = new Float32Array(this._count);
        let offset = 0;
        for (const c of this._buf) { merged.set(c, offset); offset += c.length; }
        this.port.postMessage(merged);
        this._buf = [];
        this._count = 0;
      }
    }
    return true; // keep processor alive
  }
}

registerProcessor("pcm-worklet", PCMWorklet);
