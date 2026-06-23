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

## Next diagnostic step (do this first)

Dump what the server actually receives to a WAV file and inspect it:

1. In `app.py`, temporarily write the accumulated `pcm` buffer to a WAV on SAVE
   (16 kHz, mono, 16-bit) instead of (or in addition to) transcribing.
2. Open that WAV. Check: is there audible speech? What's the RMS / peak amplitude?
   - **Silent / near-zero amplitude** → the capture path produces silence. Suspect:
     `toInt16PCM` scaling, the Float32→Int16 conversion, the worklet posting empty
     channel data, or the downsample averaging zeroing things out.
   - **Audible speech present** → the problem is server-side interpretation
     (sample rate, dtype, endianness) — but note synthetic PCM already works, so
     compare the byte layout the browser sends vs. the Python test client.

## Key files / facts

- Capture: `static/app.js` (`toInt16PCM`, `flushAudio`) + `static/worklet-processor.js`
- Server: `app.py` (`/ws`, accumulates `pcm` bytearray) → `transcriber.py` `transcribe_pcm()`
- PCM contract: raw 16-bit signed little-endian, mono, 16 kHz.
- AudioContext runs at the NATIVE rate (e.g. 48000); `toInt16PCM` downsamples to 16000.
- Server saves to `~/Desktop/transcript_YYYY-MM-DD_HHMMSS.txt`.

## Quick sanity probe in the browser console (while recording)

Check that captured floats aren't silent — paste in DevTools after Start:
the `sent N samples` line already logs counts; to check amplitude, temporarily
log `Math.max(...merged.map(Math.abs))` inside `flushAudio` — if it's ~0, the
mic samples are silent despite the count being non-zero.
