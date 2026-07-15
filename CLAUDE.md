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
Audio is captured **in Python** via `sounddevice` (PortAudio), not the embedded
WebView — see the TCC note below for why.

To install deps manually:
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## Testing

```bash
python -m pytest tests/ --ignore=tests/js -v --tb=short   # all Python tests
npm test                                                   # JS tests (vitest, tests/js/)
python -m pytest tests/test_websocket.py -v                # single file
python -m pytest tests/test_websocket.py::test_websocket_connects -v  # single test
```

Three marker-gated groups are skipped by default (see `pytest.ini`):
- `hardware` (`tests/test_audio_capture.py`) — needs a real audio input device.
- `bundle` (`tests/test_bundle.py`) — needs a built `Transcriber.app` (run `make_app.sh` first). `deploy.sh` runs these separately, post-build.
- `summarization` (`tests/test_summarizer.py`) — exercises the real GGUF model instead of the mocked one used by the rest of the suite; opt in with `TRANSCRIBER_RUN_SUMMARIZATION_TESTS=1` since it downloads a multi-GB model on first run.

CI (`.github/workflows/test.yml`) runs Python tests on Linux — darwin-only deps
(`pyobjc*`, `pywebview`, `sounddevice`) are skipped there via platform markers in
`requirements.txt`, and `main.py` imports `webview` lazily inside `__main__` so
the module still imports on Linux for the pure-logic tests. JS tests run separately via `npm install && npm test`.

`deploy.sh --test-only` runs the same pre-build suite `deploy.sh` runs before a
real build; `--build-only` skips straight to building.

## Architecture

Local audio transcription tool — nothing leaves the machine. **Two capture paths**
feed the same FastAPI server and WebSocket protocol:

```
Browser mode (run.sh, real browser or a plain browser tab):
  static/app.js  getUserMedia → AudioWorklet → Float32 → 16 kHz Int16 PCM
    └─► WebSocket /ws (binary frames) ─┐
                                       ├─► app.py (chunked accumulate+transcribe) ─► transcriber.py (faster-whisper)
Desktop mode (Transcriber.app, pywebview/WKWebView):        │
  app.js sends {"type":"start", meeting_device, mic_device} │
    └─► app.py's _python_capture() opens sounddevice        │
        InputStream(s) via audio.py, mixes samples, ────────┘
        feeds the same PCM accumulator
                        On SAVE: final tail transcription, then summarizer.py
                        (local GGUF model) summarizes the full transcript ─►
                        ~/Desktop/transcript_*.txt (summary + transcript)
```

**Capture-path selection.** The server sets `DESKTOP_CAPTURE` from the
`TRANSCRIBER_DESKTOP` env var (set by `main.py` before importing `app`). If set,
`GET /` injects `window.__DESKTOP__ = true` into `index.html`. The client picks
its capture path with `PYTHON_AUDIO = window.__DESKTOP__ === true ||
!navigator.mediaDevices` (`static/app.js`). Browser mode leaves `__DESKTOP__`
unset and always uses `getUserMedia`.

### Why desktop mode captures audio in Python, not via the WebView

An earlier version had the desktop app rely on pywebview's embedded WKWebView
`getUserMedia`, on the theory that a properly signed bundle would make WebKit
treat it like a real browser. In practice the **embedded** WKWebView's
`getUserMedia` returns silent PCM even after the mic permission prompt is
granted. The fix (see git history: "Fix desktop app: launch crash, silent
capture, choppy audio, self-relaunch") was to always capture in Python via
`sounddevice`/PortAudio for desktop builds — `audio.py` + `GET /devices` + a
JSON `{"type":"start", meeting_device, mic_device}` WebSocket frame — and drop
the WebView-capture path entirely for that mode. macOS still prompts for
microphone access because `sounddevice` opening a real input stream is what
triggers TCC, driven by `NSMicrophoneUsageDescription` + the audio-input
entitlement on the signed bundle.

### Two-input mixing (desktop mode)

Desktop mode can capture **two simultaneous input devices** — a "meeting audio"
source (e.g. a virtual loopback device like BlackHole) and a real microphone —
selected independently in the UI (`deviceSelect` / `micSelect`). In
`app.py`'s `_python_capture()`, each device gets its own `sounddevice.InputStream`
and per-stream float32 accumulator; the two streams are **summed sample-for-sample
once both have buffered a common span**, not concatenated — concatenating
interleaves 4096-sample callback blocks (A,B,A,B…), doubling duration and
gutting every other ~256ms of audio. A `MAX_BACKLOG` bound (2s) drops the
oldest excess from a fast stream so clock drift between the two independent
PortAudio streams can't grow unbounded.

**Stalled-stream watchdog.** Summing requires every configured stream to keep
advancing (`ready = min(accumulator sizes)`); a stream that stops producing
callbacks entirely — e.g. a Bluetooth mic (AirPods/Beats) that never completes
its HFP handshake, or a misbehaving device — would otherwise block the mix
forever, since `ready` stays pinned at that stream's stalled size. This was a
real regression: selecting BlackHole + a flaky Bluetooth mic produced total
silence even though BlackHole was capturing fine. The fix: a watchdog in
`_python_capture()`'s poll loop checks `last_progress[i]` per stream, and if
one stream has produced nothing for 1.5s while another is actively delivering
audio, it's added to a `dead` set and excluded from the `min()` calculation —
the healthy stream(s) then flow through unblocked. This sends a non-fatal
`{"type": "warning"}` WebSocket message (see below), never `"error"`.

**Device identity: name, not index.** `GET /devices` (and `list_input_devices()`
in `audio.py`) identify a device by its **name** (e.g. `"BlackHole 2ch"`), not
its numeric PortAudio index. Indices from `sounddevice.query_devices()` are
NOT stable — connecting or disconnecting a Bluetooth device (AirPods, Beats)
re-numbers every subsequent device in the list. A UI dropdown populated with a
cached index can silently point at the WRONG device by the time the user
clicks Start if a Bluetooth device connected/disconnected in between — this
was a real bug that made BlackHole capture fail intermittently and
unpredictably, indistinguishable from a permissions problem because it opened
successfully and produced digital silence from whatever device the stale
index now pointed to. `open_input_stream()`'s `_resolve_device_index()`
re-queries `sd.query_devices()` fresh and resolves by name at the moment the
stream actually opens, immune to any drift since the dropdown was populated.

**Warning vs. error messages.** `{"type": "error"}` is reserved for conditions
that actually end the session (the frontend's `onmessage` handler calls
`resetUI()` on it, disabling Stop & Save). Diagnostic conditions that don't
stop capture — the stalled-stream watchdog above, and the one-shot "no sound
detected in the first 5s" check — use `{"type": "warning"}` instead, which the
frontend shows as a transient status message without touching button state.
An earlier version sent the silence diagnostic as `"error"` with a message
hardcoded to blame "microphone" permissions even when no microphone was
selected at all (meeting-audio-only recording); that both showed a misleading
message and disabled Stop & Save for a condition that wasn't fatal.

**Exact-zero peak ≠ a capture bug — it means nothing is routed to the loopback
device.** BlackHole (or any virtual loopback device) only carries audio if
macOS's system *output* is actually sent to it; selecting BlackHole in
Transcriber only controls what it *listens* to. If the Mac's actual output
device is still the speakers, headphones, or a Bluetooth device, BlackHole's
input is genuinely, perfectly silent — the capture pipeline can be working
correctly end-to-end (steady per-device callback counts in the `heartbeat`
log lines, no errors, a valid WAV written) and still show `capture peak (5s
check): 0.00000` forever, because there is truly nothing arriving. This is
the single most time-consuming thing to debug from a bug report alone, because
every symptom (no transcript, no error, a "silent WAV") is identical to a real
permissions or device-resolution bug. The tell in `desktop.log`: a peak of
*exactly* `0.00000` (not just very small) across multiple attempts, with
`received_samples` in the heartbeat lines climbing at a normal, steady rate —
i.e. the stream is healthy and producing frames, they're just all zeros. The
fix isn't code — it's routing: create a Multi-Output Device in Audio MIDI
Setup containing BlackHole + the user's real output, and set that as the
system's actual output device (see `README.md`'s "Setting up meeting-audio
capture" section). A real microphone (or a Bluetooth mic like Beats) won't
read *exactly* zero even in a quiet room — actual hardware picks up some
noise floor — which is a useful way to distinguish "no signal is routed here"
(loopback device, exact zero) from "it's just quiet" (real mic, small nonzero
peak).

### macOS microphone permission (TCC) — why the app must be a real bundle

macOS binds microphone (and BlackHole/CoreAudio input) permission to **code
identity**. An earlier build shipped the app as a shell script that `exec`'d
Apple's shared `/Library/Developer/CommandLineTools/usr/bin/python3`; the app
had no real identity, so permission never stuck correctly.

The fix: build with **PyInstaller** so `Contents/MacOS/Transcriber` is a genuine
Mach-O executable with Python embedded, ad-hoc signed with `entitlements.plist`
(`com.apple.security.device.audio-input`) and `NSMicrophoneUsageDescription` in
Info.plist. `tests/test_bundle.py` (the `bundle` marker) enforces the bundle
properties so the regression cannot return.

**Install note:** on first launch, click **Allow** on the microphone prompt. The
app needs only **Microphone** permission — *not* Screen & System Audio Recording
(that's for ScreenCaptureKit, which this app does not use). If a stale grant
lingers from an old build: `tccutil reset Microphone com.lucashendrich.transcriber`
and, if needed, delete `~/Library/Application Support/Transcriber` to clear the
WebView's cached per-origin permission data.

### WebSocket protocol

Asymmetric: the client sends **binary** frames (raw PCM, browser mode only) or
**text** frames for JSON config/control (`{"type":"config","save_wav":bool}`,
`{"type":"start","meeting_device":...,"mic_device":...}`, `SAVE`, `CANCEL`). The
server replies with JSON messages tagged by `type` (`transcript`, `saved`,
`error`, `cancelled`). PCM contract (both paths): 16-bit signed little-endian,
mono, 16 kHz.

**Why raw PCM, not webm:** an earlier version sent Chrome's `MediaRecorder` webm
chunks. A webm stream that is cut mid-recording is unfinalized, and ffmpeg/PyAV
decodes **zero frames** from it — so live preview was always empty and the saved
file came out empty. Raw PCM has no container, so every slice (including a partial
buffer mid-recording) is always decodable.

### Chunked transcription with overlap

`app.py` accumulates incoming PCM into `pending_pcm`. Every ~3s (client flush
interval / server capture-loop tick) it runs a live preview pass over whatever
has accumulated so far. Once `pending_pcm` reaches `CHUNK_BYTES` (30s), that
chunk is "committed": it's transcribed with a 2s (`OVERLAP_BYTES`) prefix
carried over from the end of the previous chunk for sentence context, appended
to `completed_segments`, and `pending_pcm` resets — so the live preview is
always `completed_segments` (already finalized) + a transcription of whatever's
accumulated since the last commit. `skip_secs` tells `transcribe_pcm()` to
discard segments that fall entirely inside the overlap prefix so they aren't
duplicated. On `SAVE`, any remaining `pending_pcm` tail is transcribed once more
and appended before writing the final text file.

### Key files

| File | Purpose |
|---|---|
| `app.py` | FastAPI server — `/ws` WebSocket (chunked accumulate + overlap-stitched transcription, session reset), `/devices` endpoint, `_python_capture()` for desktop-mode sounddevice capture + two-stream mixing, WAV debug dump on SAVE (`save_wav` config flag). |
| `audio.py` | Shared audio helpers for desktop mode — `float_to_pcm16()`, `list_input_devices()` (returns devices keyed by name, not index — see above), `open_input_stream()` (resolves a device name to its current index at open time), all via sounddevice/PortAudio. Kept separate so capture is unit- and hardware-testable. |
| `main.py` | Desktop entry point — sets `TRANSCRIBER_DESKTOP=1` before importing `app`, starts uvicorn in a daemon thread, opens a pywebview window, guards against a second instance and against a multiprocessing self-relaunch (`freeze_support()`). PyInstaller's bundle entry. |
| `transcriber.py` | faster-whisper wrapper — loads Whisper `base` model once (module-level cache), `transcribe_pcm()` converts Int16 PCM → float32, runs VAD-filtered transcription, applies `skip_secs` to drop overlap-duplicated segments. |
| `summarizer.py` | llama-cpp-python wrapper — loads a local Phi-4-mini-instruct GGUF model once (module-level cache, downloaded on first use like the Whisper model), `summarize_transcript()` builds a summary prompt and runs it, map-reduce chunking transcripts too long for one context window. |
| `Transcriber.spec` / `entitlements.plist` | PyInstaller build spec and codesign entitlements (audio-input + hardened-runtime exceptions for CPython). |
| `make_app.sh` / `deploy.sh` | Build the signed `.app` (PyInstaller) / full test→build→install→verify pipeline. |
| `static/index.html` | Dark-mode UI — record/stop buttons, meeting/mic device selects, live transcript display. |
| `static/app.js` | WebSocket client. Branches on `PYTHON_AUDIO` for capture path (desktop: sends `start`/`SAVE` control frames only; browser: `getUserMedia` + AudioWorklet + `toInt16PCM` downsampling + periodic `flushAudio()`). Renders live transcript and save notice. |
| `static/worklet-processor.js` | `pcm-worklet` AudioWorkletProcessor — runs on the audio thread, buffers Float32 mic samples in ~4096-sample batches and posts them to the main thread. Browser mode only. |
| `static/style.css` | Dark theme styles |
| `run.sh` | One-command launcher — creates venv, installs deps, frees the port, auto-opens browser, starts server |

### Audio capture rationale (why it's built this way)

- Browser mode's `AudioContext` runs at the **native** hardware rate (e.g.
  44.1/48 kHz), not a forced 16 kHz — forcing 16 kHz can yield silent capture on
  some hardware. JS downsamples to 16 kHz in `toInt16PCM` instead.
- Browser capture uses an **AudioWorklet** (audio-thread `process()`), not the
  deprecated `ScriptProcessorNode`. The worklet only reads input; it's connected
  to `destination` to stay alive and outputs silence (no feedback).
- Desktop mode's `sounddevice.InputStream`s open directly at 16 kHz mono
  float32 (PortAudio resamples), so no separate downsampling step is needed
  there.

### Transcription model

- Model: `faster-whisper` with Whisper `base` (English, ~142 MB, auto-downloaded on first run)
- Runs fully on CPU with `int8` quantization — no GPU required
- Model cache stored by `faster-whisper` in `~/.cache/huggingface/`

### Recording flow

1. User clicks **Start Recording**. Browser mode: browser requests mic, opens
   WebSocket, starts a Web Audio graph. Desktop mode: opens WebSocket, sends a
   `start` frame with the chosen meeting/mic device IDs; the server opens the
   sounddevice stream(s).
2. PCM streams into the server continuously (browser: `flushAudio()` every 3s;
   desktop: `_python_capture()`'s loop). The server transcribes the accumulated
   buffer on each tick and, once a 30s chunk is complete, commits it with
   overlap stitching (see above) and sends a live transcript update.
3. User clicks **Stop & Save Meeting** → any WebSocket/Python capture is
   stopped, the remaining PCM tail is transcribed and appended to the
   committed segments. If the joined transcript is non-empty, the server
   sends a `{"type": "status"}` "Generating summary..." message and runs
   `summarizer.summarize_transcript()` on it; the saved file is the summary
   followed by the full transcript (`Summary:\n...\n\nTranscript:\n...`). If
   summarization raises for any reason, that's logged and the file falls back
   to the transcript alone — summarization can never block a save. Either
   way the result is written to `~/Desktop/transcript_YYYY-MM-DD_HHMMSS_mmm.txt`
   (falls back to `~/` if no Desktop directory exists). If "save WAV" was
   checked, the raw PCM is also dumped to a sibling `.wav` file. The `"saved"`
   WebSocket message's `text` field is always the plain transcript (not the
   summary), so the live transcript display is unaffected by summarization.
4. Session state (`pending_pcm`, `overlap_pcm`, `completed_segments`,
   `full_pcm`) is reset — no audio or text retained in memory after save.

## Environment

No API keys required. Fully offline. Optional env vars:

- `VERBOSE=1` — enables extra `[transcriber]` debug logging in `app.py` (peak
  amplitude on receipt, chunk-commit timing, capture start/stop).
- `TRANSCRIBER_DESKTOP=1` — set internally by `main.py`; forces desktop
  (Python/sounddevice) capture mode. Not meant to be set manually for the
  browser path.
- `TRANSCRIBER_APP_NAME` — overrides the app name used by `make_app.sh`,
  `Transcriber.spec`, and `main.py` (bundle name, bundle identifier, install
  path, log directory, WebView storage directory, window title, and the
  self-reactivation bundle id all derive from it). Defaults to `Transcriber`.
  Set to e.g. `Transcriber-beta` to build/install a test copy that coexists
  with the production app instead of overwriting it — see `deploy.sh --beta`.
- `TRANSCRIBER_PORT` — overrides the port used by `main.py` and `run.sh`
  (default `8765`). Needed to run a second instance concurrently, since
  `run.sh` kills whatever already holds its port on startup.
- `TRANSCRIBER_RUN_SUMMARIZATION_TESTS=1` — opts in to
  `tests/test_summarizer.py`'s real-model integration test (downloads the
  summarization GGUF model; skipped by default, see Testing above).
