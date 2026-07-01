# Transcriber — Architecture Onboarding

Local, fully-offline audio transcription tool. Nothing leaves the machine — no
API keys, no cloud calls. Whisper (`faster-whisper`, `base` model, CPU/int8)
runs in-process.

## The big picture

One FastAPI server (`app.py`) and one WebSocket protocol serve **two different
front ends**:

```
                        ┌─────────────────────────────────────────┐
                        │              app.py (FastAPI)            │
                        │  GET /            → index.html            │
                        │  GET /devices     → sounddevice input list│
                        │  WS  /ws          → session state machine │
                        └───────────────┬───────────────────────────┘
                                        │
                     ┌──────────────────┴──────────────────┐
                     │                                       │
        Browser mode (run.sh)                    Desktop mode (Transcriber.app)
        capture: JS getUserMedia                  capture: Python sounddevice
                     │                                       │
   static/app.js: AudioWorklet → Float32          app.py _python_capture():
   → 16kHz Int16 PCM → binary WS frames           opens sounddevice InputStream(s)
                     │                             for meeting_device + mic_device,
                     │                             sums them sample-for-sample
                     └──────────────┬──────────────┘
                                    ▼
                     pending_pcm accumulator (per WS session)
                                    │
                     every ~3s: live preview transcribe
                     every 30s: "commit" a chunk with 2s overlap
                     stitched in for sentence context (transcriber.py)
                                    │
                     on SAVE: transcribe remaining tail, join all
                     segments, write ~/Desktop/transcript_*.txt
```

## Why two capture paths exist

This is the single most important thing to understand before touching audio
code — it's the result of two hard-won bug fixes:

1. **Desktop mode does NOT use the WebView's `getUserMedia`.** An earlier
   version tried that (on the theory that a signed bundle would make WKWebView
   behave like a real browser). It doesn't — the *embedded* WKWebView's
   `getUserMedia` silently returns zeroed PCM even after the mic permission
   prompt is granted. Desktop mode instead captures audio **in Python** via
   `sounddevice`/PortAudio (`audio.py`), completely bypassing the WebView for
   audio. The WebView is only used to render the UI.

2. **The server tells the client which path to use**, not the other way
   around. `main.py` sets `TRANSCRIBER_DESKTOP=1` before importing `app.py`.
   `app.py` reads that into `DESKTOP_CAPTURE` and, when serving `GET /`,
   injects `window.__DESKTOP__ = true` into the HTML. `static/app.js` computes
   `PYTHON_AUDIO = window.__DESKTOP__ === true || !navigator.mediaDevices` and
   branches its entire Start/Stop button logic on that one boolean.

Browser mode (`./run.sh`) never sets any of this — it always uses
`getUserMedia` + an `AudioWorklet` (`static/worklet-processor.js`) and never
hits the TCC (macOS privacy permission) edge cases that desktop mode has to
work around.

## macOS microphone permission (TCC) — the other hard-won constraint

macOS ties microphone (and virtual-loopback-device, e.g. BlackHole) permission
to **code identity** — literally the signed binary, not "Python" in the
abstract. An earlier build shipped the desktop app as a shell script that
`exec`'d the system's shared Python; macOS attributed the mic request to that
shared interpreter, and permission never stuck to the app.

The fix: build with **PyInstaller** (`Transcriber.spec`) so
`Transcriber.app/Contents/MacOS/Transcriber` is a real Mach-O executable with
Python embedded, then ad-hoc code-sign it (`make_app.sh`) with
`entitlements.plist` (`com.apple.security.device.audio-input`) plus
`NSMicrophoneUsageDescription` in the bundle's `Info.plist`. `tests/test_bundle.py`
(pytest marker `bundle`) asserts these properties on every build so this
regression can't silently come back.

## Two-input mixing (desktop mode only)

Desktop mode can capture **two simultaneous devices** at once — a "meeting
audio" source (e.g. BlackHole, a virtual loopback device that captures
whatever's playing through your speakers) and your real microphone, picked
independently via two dropdowns in the UI.

In `app.py`'s `_python_capture()`, each device gets its own
`sounddevice.InputStream` and its own float32 accumulator buffer. The two
streams are **summed sample-for-sample** once both have buffered a common time
span — critically, *not concatenated*. An earlier bug concatenated the two
streams' ~4096-sample callback blocks (A, B, A, B, …), which doubled the
apparent duration and made every other ~256ms of audio come from the wrong
source. A small `MAX_BACKLOG` (2s) bound drops excess from whichever stream is
running ahead, so clock drift between the two independent PortAudio streams
can't grow unbounded over a long recording.

## Chunked transcription with overlap stitching

`transcriber.py` wraps `faster-whisper`. `app.py` doesn't transcribe once at
the end — it runs Whisper repeatedly while recording is in progress:

- Every ~3 seconds it runs a **live preview** pass over whatever PCM has
  accumulated since the last "commit," so the UI shows a running transcript.
- Once accumulated PCM reaches 30 seconds (`CHUNK_BYTES`), that chunk is
  **committed**: transcribed with a 2-second prefix (`OVERLAP_BYTES`) carried
  over from the tail of the *previous* chunk (so Whisper has sentence context
  across the chunk boundary), appended to `completed_segments`, and the
  pending buffer resets.
- `skip_secs` tells `transcribe_pcm()` to drop any segment that ends before
  that point — i.e. anything that falls entirely inside the overlap prefix —
  so the same words don't get transcribed twice.
- On **Stop & Save**, whatever's left in the pending buffer is transcribed one
  final time, appended, and the joined text is written to
  `~/Desktop/transcript_YYYY-MM-DD_HHMMSS.txt`.

## WebSocket protocol (`/ws`)

Asymmetric by design:
- **Binary frames** = raw PCM (browser mode only). 16-bit signed
  little-endian, mono, 16 kHz — always. No container format (no webm/wav) —
  an earlier version sent `MediaRecorder` webm chunks, but a webm stream cut
  mid-recording is unfinalized and decodes to **zero frames**, so live preview
  and the saved file were always empty. Raw PCM has no header/framing, so any
  slice (even a partial buffer) always decodes.
- **Text frames** = JSON control messages: `{"type":"config","save_wav":bool}`
  (sent once on connect), `{"type":"start","meeting_device":...,"mic_device":...}`
  (desktop mode only — tells the server which sounddevice inputs to open),
  plain-text `"SAVE"` and `"CANCEL"`.
- Server → client messages are JSON tagged by `type`: `transcript` (live
  preview text), `saved` (final text + file path), `error`, `cancelled`.

## Key files

| File | Role |
|---|---|
| `app.py` | FastAPI server: `/`, `/devices`, `/ws`. Owns the whole session state machine (PCM accumulation, chunk commit/overlap, save, reset) and the desktop-mode `_python_capture()` dual-stream mixer. |
| `audio.py` | Thin `sounddevice`/PortAudio wrapper — device enumeration, PCM conversion, stream opening. Split out so it's unit-testable without a real mic (`tests/test_audio_capture.py`, marker `hardware` for the real-device tests). |
| `transcriber.py` | `faster-whisper` wrapper. Loads the `base` model once (module-level cache). `transcribe_pcm()` does Int16→float32 conversion, VAD-filtered transcription, and overlap-segment skipping. |
| `main.py` | Desktop entry point (PyInstaller's target). Sets `TRANSCRIBER_DESKTOP=1`, starts uvicorn in a daemon thread, opens a `pywebview` window pointed at `localhost:8765`. Guards against a second app instance and against `multiprocessing`'s spawn method re-launching the whole app (`freeze_support()`). |
| `Transcriber.spec` | PyInstaller build spec — bundle identifier, Info.plist (incl. `NSMicrophoneUsageDescription`), which native packages need full data/binary collection (whisper stack, sounddevice, pywebview). |
| `entitlements.plist` | Codesign entitlements: audio-input device access + hardened-runtime exceptions CPython needs (unsigned executable memory, JIT, disabled library validation). |
| `make_app.sh` | Builds the `.icns` icon from SVG, runs PyInstaller, ad-hoc code-signs with the entitlements, registers with LaunchServices, optionally installs to `/Applications`. |
| `deploy.sh` | Full pipeline: pre-build pytest + vitest → `make_app.sh --install` → post-build `test_bundle.py` (verifies code identity/signing didn't regress). |
| `static/app.js` | The one WebSocket client, branching on `PYTHON_AUDIO` for every capture-path difference (device population, start/stop behavior). |
| `static/worklet-processor.js` | Browser-mode-only `AudioWorkletProcessor`; buffers mic samples on the audio thread and posts ~4096-sample batches to the main thread. |
| `run.sh` | Dev launcher: creates `.venv`, installs deps, frees a stale port, opens the browser, runs uvicorn directly (no bundling, no TCC concerns). |

## Two ways to run, one codebase

- **`./run.sh`** — browser mode, the "always works" developer path. No
  building, no code signing, no TCC edge cases (the browser itself owns mic
  permission).
- **`./deploy.sh`** or **`./make_app.sh --install`** — builds and installs the
  signed `Transcriber.app` for end users. This is the only path that exercises
  the Python-capture / TCC / code-signing machinery described above.

## Testing map

- `tests/test_websocket.py` — the session state machine, via Starlette's
  `TestClient` (no real server/socket needed).
- `tests/test_transcriber.py`, `tests/test_wav.py` — pure logic around
  `transcriber.py` / WAV writing.
- `tests/test_main.py` — `main.py`'s non-webview helpers (port waiting,
  single-instance guard), importable on Linux since `webview` is imported
  lazily.
- `tests/test_audio_capture.py` (marker `hardware`) — real-device
  `sounddevice` tests, skipped unless a real input device is present.
- `tests/test_bundle.py` (marker `bundle`) — asserts the built `.app`'s code
  identity/signing/Info.plist properties; only meaningful after
  `make_app.sh` has run.
- `tests/js/*.test.js` — `vitest` tests for `toInt16PCM`, capture-mode
  detection, and the worklet processor.

See [CLAUDE.md](CLAUDE.md) for exact commands.
