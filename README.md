# Transcriber

A local, offline audio transcriber. It listens to your meeting audio and/or
microphone, shows a live transcript as you talk, and saves the final text to
your Desktop when you stop. Nothing is uploaded anywhere — transcription runs
entirely on your machine.

Two ways to use it:
- **macOS**: a standalone signed `Transcriber.app` (see [Installing the Mac
  app](#installing-the-mac-app) below).
- **Any OS with Python and a browser** (Windows, Linux, or macOS without
  building the app): run the same server locally and use it in Chrome/Edge/
  Firefox (see [Running in a browser](#running-in-a-browser-windows-linux-macos)
  below).

## Requirements

- **Mac app**: macOS 12 (Monterey) or later.
- **Browser version**: Python 3.9+ and a modern browser (Chrome or Edge
  recommended). Works on Windows, Linux, and macOS.
- To transcribe **meeting audio** (what's playing through your speakers, e.g.
  a Zoom/Meet call) instead of just your microphone, you need a virtual audio
  loopback device installed first:
  - macOS: [BlackHole](https://github.com/ExistentialAudio/BlackHole)
  - Windows: enable **Stereo Mix** in Sound settings, or install a virtual
    cable driver such as [VB-Audio Virtual Cable](https://vb-audio.com/Cable/)
  Without one, Transcriber can still record your microphone — you just won't
  have a "meeting audio" device to pick from.

## Installing the Mac app

1. Get `Transcriber.app` (built from source — see below — or provided to you
   directly) and drag it into your **Applications** folder.
2. **Right-click (or Control-click) `Transcriber.app` and choose "Open"** the
   first time. Because the app isn't notarized by Apple, a normal double-click
   will be blocked by Gatekeeper ("Transcriber can't be opened because it is
   from an unidentified developer"). Using Open once bypasses this; after
   that, double-clicking works normally.
3. The app opens a window and, within a few seconds, macOS will show a
   **microphone permission prompt**. Click **Allow**. Transcriber only needs
   the **Microphone** permission — you do *not* need to grant Screen & System
   Audio Recording, since Transcriber doesn't use that.

### Building the app yourself

If you're working from the source repo instead of a pre-built app:

```bash
cd ~/Transcriber
./deploy.sh            # runs the test suite, builds, installs, and verifies
```

or, to skip the test suite and just build + install:

```bash
./make_app.sh --install
```

This builds a freshly signed `Transcriber.app` and installs it to
`/Applications`. The first build downloads several hundred MB of Python
dependencies and takes a few minutes.

## First-time use

1. Open **Transcriber** from Applications (see the Gatekeeper note above if
   this is the very first launch).
2. Grant the microphone permission prompt (see above).
3. In the app window, pick your audio sources from the two dropdowns:
   - **Meeting audio source** — pick your loopback device (e.g. "BlackHole
     2ch") to capture what's playing on your Mac, such as a call. Leave it on
     "Default device" to just use your default input.
   - **Microphone** — optionally pick your own mic to record alongside the
     meeting audio (the two are mixed together into a single transcript).
4. Click **Start Recording**. The transcript fills in live as you talk —
   Whisper transcribes in ~30-second chunks with a couple seconds of overlap
   between them for context, so don't worry if text appears a beat behind.
5. Click **Stop & Save** when you're done. The full transcript is written to
   `~/Desktop/transcript_YYYY-MM-DD_HHMMSS.txt` (falls back to your home
   folder if there's no Desktop). The app shows the save path once it's done.

**Note:** on first use ever, transcription will pause briefly while it
downloads the Whisper `base` model (~142 MB) to `~/.cache/huggingface/`. This
only happens once.

## Troubleshooting

- **"Transcriber can't be opened because it is from an unidentified
  developer"** — right-click the app and choose Open instead of
  double-clicking (see step 2 above).
- **No microphone prompt appeared / audio is silent** — open **System
  Settings → Privacy & Security → Microphone** and confirm Transcriber is
  listed and enabled. If it's missing or you need to reset it:
  ```bash
  tccutil reset Microphone com.lucashendrich.transcriber
  ```
  Then relaunch the app. If problems persist, also try removing
  `~/Library/Application Support/Transcriber` to clear cached permission data,
  then relaunch.
- **No "meeting audio" device shows up** — you need a virtual loopback driver
  like [BlackHole](https://github.com/ExistentialAudio/BlackHole) installed;
  macOS has no built-in way to capture its own audio output.
- **Nothing saved / connection lost during recording** — the app shows a
  status message if the connection drops mid-recording; stop, restart the
  app, and try again.

## Running in a browser (Windows, Linux, macOS)

You don't need to build or install anything platform-specific to use
Transcriber — the same FastAPI server runs anywhere Python does, and the
browser (not the OS) handles microphone access directly via `getUserMedia`.
This is also the fastest way to try Transcriber on macOS without building the
signed app.

### macOS / Linux

```bash
cd ~/Transcriber
./run.sh
```

This creates a Python virtual environment, installs dependencies, frees a
stale port if one is held, and opens `http://localhost:8765` in your default
browser automatically.

### Windows (Chrome)

1. Install [Python 3.9 or later](https://www.python.org/downloads/windows/)
   if you don't already have it. During install, check **"Add python.exe to
   PATH."**
2. Download or clone this repository, then open **Command Prompt** or
   **PowerShell** in the project folder.
3. Create and activate a virtual environment:
   ```powershell
   py -3 -m venv .venv
   .venv\Scripts\Activate.ps1
   ```
   (If PowerShell blocks the activation script with an execution-policy
   error, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
   first, then retry. In Command Prompt, use `.venv\Scripts\activate.bat`
   instead of the `.ps1` script.)
4. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
   (The macOS-only packages in `requirements.txt` — `pyobjc*`, `pywebview`,
   `sounddevice` — are automatically skipped on Windows; you don't need to do
   anything special for that.)
5. Start the server:
   ```powershell
   python -m uvicorn app:app --host 127.0.0.1 --port 8765
   ```
6. Open **Chrome** and go to `http://localhost:8765`.
7. Click **Start Recording**. Chrome will ask for microphone permission —
   click **Allow**. If you want to transcribe meeting/call audio too, select
   your loopback device (Stereo Mix or VB-Cable, see Requirements above) from
   the "Meeting audio" dropdown before starting.
8. Click **Stop & Save** when done. The transcript is written to
   `%USERPROFILE%\Desktop\transcript_YYYY-MM-DD_HHMMSS.txt`.

The first transcription on a fresh machine downloads the Whisper `base` model
(~142 MB, one-time, cached under your user profile).

**Windows troubleshooting:**
- `python`/`py` not recognized — reinstall Python and make sure "Add to PATH"
  was checked, or use the full path to `python.exe`.
- Windows Defender Firewall may prompt to allow Python to accept connections
  the first time you start the server — allow it (the server only listens on
  `127.0.0.1`, not your network).
- Port 8765 already in use: find and stop the process with
  `netstat -ano | findstr :8765` followed by `taskkill /PID <pid> /F`.

See [CLAUDE.md](CLAUDE.md) for the full developer reference (running tests,
architecture details) and [ONBOARDING.md](ONBOARDING.md) for a deeper
architecture walkthrough.
