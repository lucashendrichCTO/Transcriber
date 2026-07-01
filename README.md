# Transcriber

A local, offline audio transcriber for macOS. It listens to your meeting audio
and/or microphone, shows a live transcript as you talk, and saves the final
text to your Desktop when you stop. Nothing is uploaded anywhere — transcription
runs entirely on your Mac.

## Requirements

- macOS 12 (Monterey) or later
- To transcribe **meeting audio** (what's playing through your speakers, e.g.
  a Zoom/Meet call) instead of just your microphone, you need a virtual audio
  loopback device such as [BlackHole](https://github.com/ExistentialAudio/BlackHole)
  installed first. Without it, Transcriber can still record your microphone —
  you just won't have a "meeting audio" device to pick from.

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

## Developing / running from source without building the app

For development, you can run the same server in a normal browser tab instead
of building a signed app — this avoids all of the macOS permission machinery
above since the browser owns microphone access directly:

```bash
cd ~/Transcriber
./run.sh
```

This creates a Python virtual environment, installs dependencies, and opens
`http://localhost:8765` in your browser.

See [CLAUDE.md](CLAUDE.md) for the full developer reference (running tests,
architecture details) and [ONBOARDING.md](ONBOARDING.md) for a deeper
architecture walkthrough.
