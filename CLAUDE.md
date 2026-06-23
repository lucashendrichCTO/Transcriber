# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

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
    │  Web Audio API captures raw 16 kHz mono PCM (Int16)
    └─► WebSocket /ws  ──►  app.py  ──►  transcriber.py (faster-whisper)
                                │
                        Accumulates raw PCM bytes
                        Transcribes the growing buffer (live preview)
                        On SAVE command: final transcription → ~/Desktop/transcript_*.txt
```

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
| `static/app.js` | Web Audio capture (`ScriptProcessorNode`), downsamples to 16 kHz Int16, WebSocket client, sends PCM every 3 s, renders live transcript |
| `static/style.css` | Dark theme styles |
| `run.sh` | One-command launcher — creates venv, installs deps, frees the port, auto-opens browser, starts server |

### Transcription model

- Model: `faster-whisper` with Whisper `base` (English, ~142 MB, auto-downloaded on first run)
- Runs fully on CPU with `int8` quantization — no GPU required
- Model cache stored by `faster-whisper` in `~/.cache/huggingface/`

### Recording flow

1. User clicks **Start Recording** → browser requests mic, opens WebSocket, starts a Web Audio graph
2. `ScriptProcessorNode` captures Float32 samples; downsampled to 16 kHz Int16 PCM and sent every 3 seconds
3. Server accumulates the raw PCM, runs Whisper on the full buffer, returns live transcript
4. User clicks **Stop & Save** → final Whisper pass → saved to `~/Desktop/transcript_YYYY-MM-DD_HHMMSS.txt`
5. Session cleared — no audio or text retained in memory after save

## Environment

No API keys or environment variables required. Fully offline.
