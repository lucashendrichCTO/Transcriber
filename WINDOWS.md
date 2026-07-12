# Running Transcriber on Windows (Chrome)

Transcriber is a local, offline audio transcriber — it listens to your
microphone and/or meeting audio, shows a live transcript as you talk, and
saves the final text to your Desktop. Nothing is uploaded anywhere;
transcription runs entirely on your own PC.

This guide covers the **browser version**, which is the way to run
Transcriber on Windows (there's no separate Windows installer — you run a
small local server and use it in Chrome). It takes about 10 minutes the first
time, and 10 seconds every time after that.

## What you need

- **Windows 10 or 11**
- **Python 3.9 or later** (free — installed in Step 2 below if you don't have it)
- **Google Chrome** (Edge also works, since both are Chromium-based)
- A microphone (built-in laptop mic is fine) for basic use. To also capture
  **meeting/call audio** (not just your voice), see [Capturing meeting
  audio](#capturing-meeting-audio-optional) near the end — that part is
  optional and can be set up later.

## Step 1 — Download the code

This repository is private, so you'll need to be signed into the GitHub
account it was shared with you on.

1. Go to the repository on GitHub and make sure the branch selector (top-left
   of the file list, next to a little branch icon) is set to **`windows-browser`**
   — not `main`. The Windows setup guide (this file) and Windows-specific
   notes only exist on that branch.
2. Click the green **Code** button → **Download ZIP**.
3. Extract the ZIP somewhere easy to find, e.g. `Documents\Transcriber`.

*(If you already have Git installed, `git clone -b windows-browser <repo-url>`
works too.)*

## Step 2 — Install Python

Skip this if `python --version` in a terminal already shows 3.9 or later.

1. Go to [python.org/downloads/windows](https://www.python.org/downloads/windows/)
   and download the latest Python 3 installer.
2. Run it. **On the very first installer screen, check the box that says
   "Add python.exe to PATH"** at the bottom — this is the single most common
   thing people miss, and without it none of the commands below will work.
3. Click **Install Now** and let it finish.

## Step 3 — Open a terminal in the Transcriber folder

1. Open the `Transcriber` folder you extracted in Step 1, in File Explorer.
2. Click the address bar, type `powershell`, and press **Enter**. This opens
   PowerShell already pointed at that folder. (Alternative: right-click
   inside the folder → "Open in Terminal", if your Windows version has that
   option.)

## Step 4 — Set up and start Transcriber

Copy and paste each block below into the PowerShell window one at a time,
pressing Enter after each.

**Create a private Python environment for Transcriber** (only needed once):
```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
```
> If you see a red error mentioning "execution policy" or "running scripts is
> disabled," run this line first, then retry the line above:
> ```powershell
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
> ```
> This only relaxes the restriction for this one PowerShell window, not your
> whole system.

**Install Transcriber's dependencies** (only needed once — takes a couple of
minutes):
```powershell
pip install -r requirements.txt
```

**Start the server** (do this every time you want to use Transcriber):
```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8765
```
Leave this PowerShell window open — it's running the app. Closing it stops
Transcriber.

## Step 5 — Open it in Chrome

1. Open **Chrome**.
2. Go to: **`http://localhost:8765`**
3. You should see the Transcriber page with a **Start Recording** button.

## Step 6 — Use it

1. Click **Start Recording**. Chrome will ask for microphone permission the
   first time — click **Allow**.
2. Talk normally. Text will start appearing after a few seconds and keeps
   updating as you speak (Transcriber processes audio in ~30-second chunks,
   so there's a short natural delay — that's expected, not a bug).
3. Click **Stop & Save** when you're done. The transcript is saved to:
   ```
   %USERPROFILE%\Desktop\transcript_YYYY-MM-DD_HHMMSS.txt
   ```
   (that's your regular Windows Desktop folder — e.g.
   `C:\Users\<yourname>\Desktop`).

**The very first time you transcribe anything**, there will be an extra pause
of maybe a minute while it downloads the speech-recognition model (~142 MB,
one-time only, saved for all future use).

## Using it again later

You don't need to repeat Steps 1–4 in full. Next time:
1. Open PowerShell in the Transcriber folder (Step 3).
2. Run:
   ```powershell
   .venv\Scripts\Activate.ps1
   python -m uvicorn app:app --host 127.0.0.1 --port 8765
   ```
3. Open `http://localhost:8765` in Chrome.

## Capturing meeting audio (optional)

By default, Transcriber only captures your microphone. To also capture
**audio playing on your PC** (a Zoom/Teams call, a video, etc.) so it gets
transcribed too, Windows needs a way to "loop back" its own output as a
recordable input. Pick one:

**Option A — Stereo Mix (built-in, if your sound card supports it)**
1. Right-click the speaker icon in the Windows taskbar → **Sound settings**
   → **More sound settings** (opens the classic Control Panel dialog).
2. Click the **Recording** tab.
3. Right-click empty space in the list → check **"Show Disabled Devices"**.
4. If **Stereo Mix** appears, right-click it → **Enable**.
5. In Transcriber's "Meeting audio" dropdown, select **Stereo Mix**.

Many modern laptops (especially with Realtek replaced by other drivers) don't
expose Stereo Mix at all — if it's not in that list even with disabled
devices shown, use Option B instead.

**Option B — VB-Audio Virtual Cable (works on any Windows PC)**
1. Download and install [VB-Audio Virtual Cable](https://vb-audio.com/Cable/)
   (free).
2. After installing, set your PC's Sound output to **CABLE Input** — this
   means you'll only hear audio through the cable, not your speakers, unless
   you also set up a way to hear it (VB-Cable's docs cover this if you need
   it; not required just to capture and transcribe).
3. In Transcriber's "Meeting audio" dropdown, select **CABLE Output**.

## Troubleshooting

- **`python` or `py` is not recognized** — Python wasn't added to PATH during
  install. Re-run the Python installer, choose "Modify," and make sure "Add
  python.exe to PATH" is checked. Close and reopen PowerShell afterward.
- **PowerShell won't run `Activate.ps1`, mentioning execution policy** — run
  `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first (see
  Step 4), then try again.
- **A Windows Defender Firewall popup appears** the first time you start the
  server — click **Allow access**. The server only listens on your own PC
  (`127.0.0.1`), never your network, so this is safe.
- **"Port 8765 is already in use"** — something's already running (maybe an
  earlier copy of Transcriber you forgot to close). Find and stop it:
  ```powershell
  netstat -ano | findstr :8765
  taskkill /PID <the number from the previous command> /F
  ```
- **No microphone prompt appeared, or the transcript stays empty** — check
  Windows' own microphone privacy setting: **Settings → Privacy & security →
  Microphone**, and make sure Chrome is allowed access.
- **Meeting audio (Stereo Mix / VB-Cable) shows in the dropdown but the
  transcript stays silent** — this almost always means your PC's actual sound
  **output** isn't going through that device. Selecting a device in
  Transcriber only controls what it *listens* to; Windows still has to be
  told to *send* audio there. Re-check Option A/B above — for Stereo Mix,
  audio just needs to be playing normally, since Stereo Mix mirrors whatever
  the sound card outputs; for VB-Cable, your Windows output device must
  actually be set to CABLE Input.
- **Nothing saved / "Connection lost" message** — the PowerShell window
  running the server may have been closed, or your PC went to sleep. Reopen
  it (see "Using it again later" above) and start again.

## Something not covered here?

See the main [README.md](README.md) for the macOS app and general project
overview, or [CLAUDE.md](CLAUDE.md) / [ONBOARDING.md](ONBOARDING.md) for how
Transcriber works under the hood.
