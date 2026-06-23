# DEBUGGING — live transcription empty

Current open bug: live transcription never appears and the saved `.txt` is empty,
even though the browser console shows audio is being captured and sent.

## Verified working (don't re-test these)

- **Whisper model + VAD + PyAV decode** — transcribing a complete AIFF/WAV returns
  correct text. (`base` model, CPU, int8.)
- **`transcribe_pcm()`** — feeding 16 kHz mono Int16 PCM (full *and* truncated
  halves) returns correct text.
- **Server WebSocket path end-to-end** — a Python test client that streams real
  16 kHz Int16 PCM to `/ws` gets correct incremental previews AND a non-empty saved
  file. So `app.py` + `transcriber.py` are correct when fed valid PCM.
- **Browser capture fires** — console logs show `captured N samples` growing and
  `sent N bytes` increasing while speaking. So getUserMedia + AudioWorklet + the
  WebSocket send are all running.

## Therefore the fault is almost certainly the PCM CONTENT the browser sends

Captured-and-sent but empty transcription ⇒ the bytes arriving server-side are
probably silence / near-zero / mis-scaled, so VAD strips everything.

## Diagnostic instrumentation added (2026-06-23)

Two diagnostic tools are now wired in:

### 1. Browser amplitude logging (`static/app.js`)

Every `flushAudio()` call now logs the peak Float32 amplitude before downsampling:

```
[transcriber] flush peak amplitude: 0.3712 (144384 float32 samples @ 48000 Hz)
```

If this reads `0.0000` or `< 0.001` you get a WARNING. That means mic samples are
silent — the capture path is broken before `toInt16PCM` even runs.

**Interpretation:**
- `peak > 0.01` → audio data is real; problem is downstream (server-side or VAD)
- `peak < 0.001` → audio is silent in JS; fix is in getUserMedia / AudioWorklet

### 2. Server WAV dump (`app.py`)

On every SAVE, `app.py` writes a `.wav` file alongside the transcript:

```
~/Desktop/transcript_2026-06-23_143012_debug.wav
```

This is controlled by the `DEBUG_WAV` env variable (default ON, set `DEBUG_WAV=0`
to disable). The server log prints:

```
[transcriber] debug WAV saved: /Users/.../transcript_..._debug.wav  (512000 bytes, ~16.0s)
```

Open the WAV in QuickTime, Audacity, or run `afplay` to hear what the server received.

**Interpretation:**
- **Audible speech** → audio is reaching the server correctly; VAD threshold may be too
  aggressive, or the sample rate is being misread. Try `vad_filter=False` in `transcriber.py`.
- **Silence / flat line** → PCM content is zero. The fault is in JS (`toInt16PCM` math or
  Float32Array scaling). Check the browser amplitude logs first.
- **Garbled / chipmunk audio** → sample rate mismatch. The server is assuming 16 kHz but the
  browser may be sending at a different rate. Verify `audioCtx.sampleRate` log matches
  `toInt16PCM` downsampling target.

## Next steps (ordered)

1. Record something, click Stop & Save, check browser console for peak amplitude value
2. Open the `_debug.wav` on the Desktop and listen
3. Based on what you find, go to the relevant section above for the fix

## Key files / facts

- Capture: `static/app.js` (`toInt16PCM`, `flushAudio`) + `static/worklet-processor.js`
- Server: `app.py` (`/ws`, accumulates `pcm` bytearray) → `transcriber.py` `transcribe_pcm()`
- PCM contract: raw 16-bit signed little-endian, mono, 16 kHz.
- AudioContext runs at the NATIVE rate (e.g. 48000); `toInt16PCM` downsamples to 16000.
- Server saves to `~/Desktop/transcript_YYYY-MM-DD_HHMMSS.txt`.
