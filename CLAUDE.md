# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Safety Rules

- **Never delete system files without asking first.** This includes any file not explicitly created as part of this project — OS files, hidden config files, `.venv/` contents, model cache files, or anything outside the project tree. Always confirm with the user before any destructive file operation.

## Running the Project

There are **two ways to run**, sharing the same FastAPI server and UI:

**1. Browser mode (developer / always-works path):**
```bash
cd ~/Transcriber
./run.sh
```
Creates a `.venv/`, installs deps, starts the server at `http://localhost:8765`, and
opens your browser. Audio is captured **in the browser** via `getUserMedia` +
AudioWorklet — the browser owns the macOS microphone permission, so this path
never has TCC problems.

**2. Desktop app (standalone signed bundle):**
```bash
./deploy.sh            # test → build → install → verify
# or just build:
./make_app.sh --install
```
Builds `Transcriber.app` via **PyInstaller** and installs to `/Applications`.
Audio is captured **in Python** via `sounddevice` (PortAudio). See the TCC note below.

To install deps manually:
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## Architecture

Local audio transcription tool — nothing leaves the machine. **Two capture paths**
feed the same server; the client auto-detects which to use (`PYTHON_AUDIO =
!navigator.mediaDevices`):

```
Browser mode (run.sh, real browser):
  static/app.js  AudioWorklet → Float32 → 16 kHz Int16 PCM
    └─► WebSocket /ws (binary frames) ─┐
                                       ├─► app.py ─► transcriber.py (faster-whisper)
Desktop mode (Transcriber.app, WKWebView):  │
  app.js sends {"type":"start",...} ──► app.py captures via audio.py (sounddevice)
                                       ─┘        │
                                  Accumulates raw PCM, live-preview transcribes
                                  On SAVE: final transcription → ~/Desktop/transcript_*.txt
```

**Desktop mode uses WebView capture.** Once the app is a real signed bundle (see
below), `navigator.mediaDevices` *is* available inside pywebview's WKWebView, so
the desktop app captures audio with `getUserMedia` + AudioWorklet exactly like the
real browser — WebKit shows an "Allow … to use your microphone" prompt on first
use. The Python `sounddevice` path (`audio.py` + `GET /devices` + a JSON
`{"type":"start",...}` frame) remains as an automatic fallback for any environment
where `navigator.mediaDevices` is missing (`PYTHON_AUDIO = !navigator.mediaDevices`).

### macOS microphone permission (TCC) — why the app must be a real bundle

macOS binds microphone (and BlackHole/CoreAudio input) permission to **code
identity**, and WKWebView only offers `navigator.mediaDevices` to an app with a
proper identity + `NSMicrophoneUsageDescription`. An earlier build shipped the app
as a shell script that `exec`'d Apple's shared
`/Library/Developer/CommandLineTools/usr/bin/python3`; the app had no real identity,
so `navigator.mediaDevices` was unavailable and mic access never worked.

The fix: build with **PyInstaller** so `Contents/MacOS/Transcriber` is a genuine
Mach-O executable with Python embedded, ad-hoc signed with `entitlements.plist`
(`com.apple.security.device.audio-input`) and `NSMicrophoneUsageDescription` in
Info.plist. With a real identity, WebKit grants `getUserMedia` and shows its
microphone prompt. `tests/test_bundle.py` enforces the bundle properties so the
regression cannot return.

**Install note:** on first launch, click **Allow** on the microphone prompt. The
app needs only **Microphone** permission — *not* Screen & System Audio Recording
(that's for ScreenCaptureKit, which this app does not use). If a stale grant
lingers from an old build: `tccutil reset Microphone com.lucashendrich.transcriber`
and, if needed, delete `~/Library/Application Support/Transcriber` to clear the
WebView's cached per-origin permission.

The WebSocket protocol is asymmetric: the client sends **binary** frames (raw
PCM) for audio and **text** frames for control commands (`SAVE`, `CANCEL`). The
server replies with JSON messages tagged by `type` (`transcript`, `saved`,
`error`, `cancelled`). PCM contract: 16-bit signed little-endian, mono, 16 kHz.
Note `CANCEL` is implemented server-side but the UI has no button wired to it.

**Why raw PCM, not webm:** an earlier version sent Chrome's `MediaRecorder` webm
chunks. A webm stream that is cut mid-recording is unfinalized, and ffmpeg/PyAV
decodes **zero frames** from it — so live preview was always empty and the saved
file came out empty. Raw PCM has no container, so every slice (including a partial
buffer mid-recording) is always decodable.

### Key files

| File | Purpose |
|---|---|
| `app.py` | FastAPI server — `/ws` WebSocket, `/devices` endpoint, accumulates raw PCM, calls transcriber, saves file. Handles both browser binary PCM and Python `sounddevice` capture (JSON `start` frame). Skips a live-preview pass if one is still running. |
| `audio.py` | Shared audio helpers for desktop mode — `float_to_pcm16()`, `list_input_devices()`, `open_input_stream()` (sounddevice/PortAudio). Kept separate so capture is unit- and hardware-testable. |
| `main.py` | Desktop entry point — starts uvicorn in a daemon thread, opens a pywebview window, triggers the mic-permission prompt at launch. PyInstaller's bundle entry. |
| `transcriber.py` | faster-whisper wrapper — loads Whisper `base` model, `transcribe_pcm()` converts Int16 PCM → float32 numpy array |
| `Transcriber.spec` / `entitlements.plist` | PyInstaller build spec and codesign entitlements (audio-input + hardened-runtime exceptions for CPython). |
| `make_app.sh` / `deploy.sh` | Build the signed `.app` (PyInstaller) / full test→build→install→verify pipeline. |
| `static/index.html` | Dark-mode UI — record/stop buttons, live transcript display |
| `static/app.js` | WebSocket client + main-thread audio: opens `/ws`, downsamples worklet batches to 16 kHz Int16 (`toInt16PCM`), `flushAudio()` sends PCM every 3 s, renders live transcript |
| `static/worklet-processor.js` | `pcm-worklet` AudioWorkletProcessor — runs on the audio thread, buffers Float32 mic samples in ~4096-sample batches and posts them to the main thread |
| `static/style.css` | Dark theme styles |
| `run.sh` | One-command launcher — creates venv, installs deps, frees the port, auto-opens browser, starts server |

### Audio capture rationale (why it's built this way)

- The `AudioContext` runs at the **native** hardware rate (e.g. 44.1/48 kHz), not a
  forced 16 kHz — forcing 16 kHz can yield silent capture on some hardware. JS
  downsamples to 16 kHz in `toInt16PCM` instead.
- Capture uses an **AudioWorklet** (audio-thread `process()`), not the deprecated
  `ScriptProcessorNode`. The worklet only reads input; it's connected to
  `destination` to stay alive and outputs silence (no feedback).

### Transcription model

- Model: `faster-whisper` with Whisper `base` (English, ~142 MB, auto-downloaded on first run)
- Runs fully on CPU with `int8` quantization — no GPU required
- Model cache stored by `faster-whisper` in `~/.cache/huggingface/`

### Recording flow

1. User clicks **Start Recording** → browser requests mic, opens WebSocket, starts a Web Audio graph
2. `pcm-worklet` captures Float32 samples; downsampled to 16 kHz Int16 PCM and sent every 3 seconds
3. Server accumulates the raw PCM, runs Whisper on the full buffer, returns live transcript
4. User clicks **Stop & Save** → final Whisper pass → saved to `~/Desktop/transcript_YYYY-MM-DD_HHMMSS.txt`
5. Session cleared — no audio or text retained in memory after save

## Known open issue

See `DEBUGGING.md`: live transcription can come back empty and the saved file
empty, despite the browser console confirming audio is captured and sent. The
server path and `transcribe_pcm()` are verified correct against synthetic PCM, so
the suspected fault is the *content* of the PCM the browser sends (silence /
mis-scaled samples that VAD strips). The documented next step is to dump the
server's accumulated `pcm` buffer to a WAV on SAVE and inspect amplitude before
changing anything else.

## Environment

No API keys or environment variables required. Fully offline.
