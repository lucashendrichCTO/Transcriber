# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Safety Rules

- **Never delete system files without asking first.** This includes any file not explicitly created as part of this project — OS files, hidden config files, `.venv/` contents, model cache files, or anything outside the project tree. Always confirm with the user before any destructive file operation.

## Running the Project

```bash
cd ~/Transcriber
./run.sh
```

First run creates a `.venv/`, installs Python deps, and downloads the Whisper `base` model (~142 MB). Server starts at `http://localhost:8765`.

To install deps manually:
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## Architecture

Local audio transcription tool — nothing leaves the machine.

```
Browser (static/)
    │  AudioWorklet captures Float32 @ native rate, downsampled in JS
    │  to raw 16 kHz mono PCM (Int16), sent every 3 s
    └─► WebSocket /ws  ──►  app.py  ──►  transcriber.py (faster-whisper)
                                │
                        Accumulates raw PCM bytes
                        Transcribes the growing buffer (live preview)
                        On SAVE command: final transcription → ~/Desktop/transcript_*.txt
```

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
| `app.py` | FastAPI server — WebSocket endpoint, accumulates raw PCM, calls transcriber, saves file. Skips a live-preview pass if one is still running so transcriptions don't pile up. |
| `transcriber.py` | faster-whisper wrapper — loads Whisper `base` model, `transcribe_pcm()` converts Int16 PCM → float32 numpy array |
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
