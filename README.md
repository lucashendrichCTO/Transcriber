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
  installed **and routed as described below**. Without it, Transcriber can
  still record your microphone — you just won't have a "meeting audio" device
  to pick from.

### Setting up meeting-audio capture (BlackHole)

Installing BlackHole is not enough by itself — selecting it in Transcriber
only tells the app which device to *listen* to. macOS's system audio still
has to actually be *sent* there, or BlackHole has nothing to capture (it will
open and "work" but produce pure digital silence, which looks exactly like a
broken app). Two steps, done once:

1. Install [BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole).
2. Open **Audio MIDI Setup** (Applications → Utilities), click the **+** in
   the bottom-left corner → **Create Multi-Output Device**, and check both
   **BlackHole 2ch** and your normal output (e.g. "MacBook Pro Speakers" or
   your headphones). This plays audio out loud as usual *and* duplicates it
   into BlackHole at the same time — the alternative (setting output directly
   to BlackHole) would make you unable to hear anything yourself.

Whenever you want to record meeting audio: set **System Settings → Sound →
Output** to that **Multi-Output Device**, then select **BlackHole 2ch** as the
meeting audio source inside Transcriber. Switch your Mac's output back to your
speakers/headphones afterward if you're not recording (a Multi-Output Device
can be a little awkward for everyday volume-key/AirPods behavior).

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
     "Default device" to just use your default input. **Before starting**,
     make sure System Settings → Sound → Output is set to the Multi-Output
     Device described above — if it's still set to your speakers/headphones/
     Bluetooth device directly, BlackHole will capture nothing at all.
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
- **BlackHole is selected but the transcript stays empty / the saved WAV is
  silent, even though the app looks like it's recording** — this is almost
  always the system output not actually being routed to BlackHole. Selecting
  BlackHole in Transcriber only chooses what it *listens* to; macOS still has
  to be told to *send* audio there. Check **System Settings → Sound → Output**
  — if it's set to your speakers, headphones, or a Bluetooth device instead of
  the Multi-Output Device from the setup steps above, BlackHole receives
  nothing and will faithfully report exact silence. This is not a bug in the
  app; see [Setting up meeting-audio capture](#setting-up-meeting-audio-capture-blackhole)
  above.
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

## License

Transcriber is released under the [MIT License](LICENSE).

### Third-party components

Transcriber is built on top of the following open-source projects (installed
via `pip`/`npm`, not vendored in this repository):

| Component | License |
|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) / [CTranslate2](https://github.com/OpenNMT/CTranslate2) | MIT |
| [FastAPI](https://github.com/tiangolo/fastapi) | MIT |
| [Starlette](https://github.com/encode/starlette) / [Uvicorn](https://github.com/encode/uvicorn) / [websockets](https://github.com/python-websockets/websockets) / [httpx](https://github.com/encode/httpx) | BSD-3-Clause |
| [NumPy](https://github.com/numpy/numpy) | BSD-3-Clause |
| [Requests](https://github.com/psf/requests) / [huggingface_hub](https://github.com/huggingface/huggingface_hub) / [tokenizers](https://github.com/huggingface/tokenizers) | Apache-2.0 |
| [onnxruntime](https://github.com/microsoft/onnxruntime) | MIT |
| [PyObjC](https://github.com/ronaldoussoren/pyobjc) | MIT |
| [pywebview](https://github.com/r0x0r/pywebview) | BSD-3-Clause |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) | MIT |
| [certifi](https://github.com/certifi/python-certifi) | MPL-2.0 |
| [Vitest](https://github.com/vitest-dev/vitest) (dev/test only) | MIT |

All of the above are permissive licenses — none require Transcriber's own
source to be released under any particular license, and none are vendored or
redistributed within this repository (they're fetched from PyPI/npm by
`pip`/`npm` at install time).

`Transcriber.spec`/`make_app.sh` use [PyInstaller](https://github.com/pyinstaller/pyinstaller)
as a **build-only tool** (GPLv2-or-later) to produce the signed macOS app; it
is never imported or distributed as part of the running application. PyInstaller's
license includes an explicit exception permitting it to build and distribute
software under any license, including this one.

The Whisper speech-recognition model (downloaded automatically on first run
to `~/.cache/huggingface/`, not included in this repository) is a separate,
MIT-licensed model published by OpenAI / SYSTRAN, retrieved directly from
Hugging Face under its own terms.
