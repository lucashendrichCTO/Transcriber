import asyncio
import datetime
import json
import os
import sys
import wave
from pathlib import Path

import numpy as np

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from audio import float_to_pcm16, list_input_devices, open_input_stream
from logutil import make_file_logger
from summarizer import summarize_transcript
from transcriber import transcribe_pcm

app = FastAPI()

_desktop = Path.home() / "Desktop"
SAVE_DIR = _desktop if _desktop.exists() else Path.home()

VERBOSE = os.environ.get("VERBOSE", "0") == "1"

# Resolve bundled assets against the app root, not the process working
# directory. PyInstaller unpacks data files (the spec's ("static", "static"))
# under sys._MEIPASS; for a plain run, they sit next to this file. Using a
# relative "static" path crashes the desktop app on Finder launch, where the
# working directory is "/" instead of the project folder.
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
STATIC_DIR = BASE_DIR / "static"

# Desktop (pywebview) mode captures audio in Python via sounddevice; the browser
# build (run.sh) captures via getUserMedia. main.py sets this before importing.
DESKTOP_CAPTURE = os.environ.get("TRANSCRIBER_DESKTOP") == "1"

# A double-clicked GUI app has no visible stdout, so plain print() vanishes —
# main.py already learned this and writes its own messages to a log file.
# app.py's capture diagnostics (stream open/callback/silence info) previously
# only used print(), meaning every capture failure in the real packaged app
# was completely invisible. Mirror main.py's log file (via the same shared
# helper) so both interleave — only in desktop mode, since browser mode has a
# real terminal. Namespaced by TRANSCRIBER_APP_NAME so a beta build's log
# never mixes with production's.
_write_log_file = make_file_logger(os.environ.get("TRANSCRIBER_APP_NAME", "Transcriber"))


def log(msg: str) -> None:
    if DESKTOP_CAPTURE:
        _write_log_file(msg)
    else:
        print(msg, flush=True)


# 30-second chunks at 16 kHz / 16-bit mono = 960,000 bytes
CHUNK_BYTES = 30 * 16000 * 2
# 2-second overlap prepended to each chunk so Whisper has sentence context
OVERLAP_BYTES = 2 * 16000 * 2

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _write_wav(pcm_bytes: bytes, path: Path, sample_rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)


@app.get("/")
async def index():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    if DESKTOP_CAPTURE:
        # Tell the client to use the Python (sounddevice) capture path instead of
        # the WebView's getUserMedia, which yields silent audio when embedded.
        html = html.replace(
            '<script src="/static/app.js"></script>',
            '<script>window.__DESKTOP__ = true;</script>\n'
            '  <script src="/static/app.js"></script>',
        )
    return HTMLResponse(html)


@app.get("/devices")
async def list_devices():
    """Return audio input devices via PortAudio (sounddevice)."""
    devices = list_input_devices()
    log(f"[transcriber] /devices → {devices}")
    return JSONResponse({"devices": devices})


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    # Per-session PCM accumulators
    pending_pcm: bytearray = bytearray()
    overlap_pcm: bytes = b""
    completed_segments: list[str] = []
    full_pcm: bytearray = bytearray()

    save_wav: bool = False
    previewing = False

    # Tracks whether anything has happened since the last SAVE (new audio
    # bytes, a new "start", or a CANCEL). A SAVE that arrives with the exact
    # same activity count as the last SAVE is a spurious duplicate — e.g. two
    # "SAVE" frames delivered back-to-back from one client action — not a
    # deliberate second save, and is answered by resending the prior response
    # rather than writing a second file for a session that hasn't changed.
    activity_seq = 0
    last_save: tuple[int, dict] | None = None

    # Python-side audio capture (pywebview / desktop mode)
    _capture_stop = asyncio.Event()
    _capture_task: asyncio.Task | None = None

    def _reset_session():
        nonlocal pending_pcm, overlap_pcm, completed_segments, full_pcm
        pending_pcm = bytearray()
        overlap_pcm = b""
        completed_segments = []
        full_pcm = bytearray()

    async def _run_preview():
        """Transcribe accumulated PCM and send a live transcript update."""
        nonlocal previewing, pending_pcm, overlap_pcm
        if previewing or not pending_pcm:
            return
        previewing = True
        loop = asyncio.get_running_loop()
        try:
            if len(pending_pcm) >= CHUNK_BYTES:
                to_transcribe = overlap_pcm + bytes(pending_pcm)
                skip_secs = len(overlap_pcm) / 32000.0
                new_overlap = bytes(pending_pcm[-OVERLAP_BYTES:])
                pending_pcm = bytearray()
                if VERBOSE:
                    log(f"[transcriber] committing chunk ({len(to_transcribe)/32000:.0f}s)")
                text = await loop.run_in_executor(
                    None, transcribe_pcm, to_transcribe, 16000, skip_secs
                )
                if text:
                    completed_segments.append(text)
                overlap_pcm = new_overlap
                preview = " ".join(completed_segments)
            else:
                to_transcribe = overlap_pcm + bytes(pending_pcm)
                skip_secs = len(overlap_pcm) / 32000.0
                text = await loop.run_in_executor(
                    None, transcribe_pcm, to_transcribe, 16000, skip_secs
                )
                preview = " ".join(filter(None, completed_segments + [text]))
            await ws.send_json({"type": "transcript", "text": preview})
        except Exception as exc:
            log(f"[transcriber] preview error: {exc}")
            await ws.send_json({"type": "error", "text": f"Preview failed: {exc}"})
        finally:
            previewing = False

    async def _python_capture(meeting_device: str, mic_device: str) -> None:
        """Capture audio via sounddevice (PortAudio) and feed mixed PCM into the
        accumulators.

        Supports one or two input streams (meeting audio + your microphone). The
        streams are time-aligned and SUMMED sample-for-sample, not concatenated.
        Concatenating two streams interleaves them block-by-block: each callback
        delivers a 4096-sample block, so the buffer becomes A,B,A,B… — which
        doubles the duration and makes the audio choppy (every other 256 ms is the
        other source). When the second source is silent that reads as 256 ms of
        audio / 256 ms of silence, and Whisper mangles the chopped words.

        Summing requires ALL configured streams to keep advancing — if one stalls
        completely (e.g. a Bluetooth mic that never finishes its HFP handshake, or
        a wrong/disconnected device), the other stream's audio piles up behind it
        and nothing is ever emitted, i.e. total silence even though one source is
        working fine. A watchdog below detects a stream that's produced nothing
        for 1.5s while another is actively delivering audio and drops it from the
        mix so the healthy stream isn't blocked forever.

        Per-stream float32 accumulators are mutated only on the event-loop thread
        (callbacks marshal frames via call_soon_threadsafe, and the watchdog runs
        on the event loop too), so no locks are needed.
        """
        loop = asyncio.get_running_loop()
        _capture_stop.clear()

        # Distinct input streams to capture. Dedupe so selecting the same device
        # for both "meeting" and "mic" doesn't double it.
        devices: list[str] = [meeting_device]
        roles: list[str] = ["meeting audio"]
        if mic_device and mic_device != meeting_device:
            devices.append(mic_device)
            roles.append("microphone")

        accums: list[np.ndarray] = [np.zeros(0, dtype=np.float32) for _ in devices]
        received_samples: list[int] = [0 for _ in devices]
        last_progress: list[float] = [loop.time() for _ in devices]
        dead: set[int] = set()
        # Bound clock drift between independent streams: never let one buffer get
        # more than ~2 s ahead of the slowest one (drop the oldest excess instead).
        MAX_BACKLOG = 2 * 16000
        stats = {"emitted_bytes": 0}

        def _flush() -> None:
            """Mix and emit the span common to all currently-live streams."""
            live = [i for i in range(len(accums)) if i not in dead]
            if not live:
                return
            ready = min(accums[i].size for i in live)
            if ready <= 0:
                return
            mixed = accums[live[0]][:ready].astype(np.float32, copy=True)
            for i in live[1:]:
                mixed += accums[i][:ready]
            for i in live:
                accums[i] = accums[i][ready:]
            pcm = float_to_pcm16(mixed)
            pending_pcm.extend(pcm)
            if save_wav:
                full_pcm.extend(pcm)
            stats["emitted_bytes"] += len(pcm)

        def _ingest(idx: int, mono: np.ndarray) -> None:
            accums[idx] = np.concatenate((accums[idx], mono))
            received_samples[idx] += mono.size
            last_progress[idx] = loop.time()
            if accums[idx].size > MAX_BACKLOG:
                accums[idx] = accums[idx][-MAX_BACKLOG:]
            _flush()

        def _make_cb(idx: int):
            def _cb(indata, frames, time_info, status):
                # Copy off PortAudio's reused buffer; mix down to mono (first channel).
                mono = np.array(indata[:, 0], dtype=np.float32)
                loop.call_soon_threadsafe(_ingest, idx, mono)
            return _cb

        streams: list = []
        try:
            for idx, dev in enumerate(devices):
                log(f"[transcriber] opening stream idx={idx} role={roles[idx]!r} device={dev!r}")
                streams.append(open_input_stream(dev, _make_cb(idx)))
            for s in streams:
                s.start()
            log(f"[transcriber] Python capture started — devices={devices} roles={roles} streams={len(streams)}")
        except Exception as exc:
            log(f"[transcriber] capture init error: {exc}")
            await ws.send_json({"type": "error", "text": f"Audio capture failed: {exc}"})
            return

        start_time = loop.time()
        last_preview = start_time
        last_heartbeat = start_time
        reported_silence = False
        try:
            while not _capture_stop.is_set():
                await asyncio.sleep(0.1)
                now = loop.time()

                # Heartbeat for the first ~6s so a real run's log shows exactly
                # what each stream produced, independent of whether any of the
                # diagnostics below ever trigger.
                if now - start_time <= 6.0 and now - last_heartbeat >= 1.0:
                    log(f"[transcriber] heartbeat t={now - start_time:.1f}s received_samples={received_samples} pending_pcm_bytes={len(pending_pcm)}")
                    last_heartbeat = now

                # Watchdog: a stream that's produced nothing for 1.5s while another
                # is actively delivering audio gets dropped from the mix so it can't
                # block the healthy stream forever (see docstring above). This is a
                # non-fatal warning — capture continues uninterrupted either way.
                if len(devices) > 1:
                    for i in range(len(devices)):
                        if i in dead:
                            continue
                        stalled = now - last_progress[i] > 1.5
                        others_alive = any(
                            received_samples[j] > 0 for j in range(len(devices)) if j != i
                        )
                        if stalled and others_alive:
                            dead.add(i)
                            log(f"[transcriber] WARNING: {roles[i]} produced no audio for 1.5s — dropping it from the mix")
                            await ws.send_json({
                                "type": "warning",
                                "text": f"No audio detected from your {roles[i]} — continuing with the "
                                        f"other source only. Check that the right device is selected and, "
                                        f"for a microphone, that it isn't muted and has access in System "
                                        f"Settings → Privacy & Security → Microphone.",
                            })
                            _flush()  # drain whatever the surviving stream already buffered

                # One-shot diagnostic ~5s in, keyed on WALL-CLOCK time (not on
                # emitted_bytes) so it still fires even if literally zero bytes
                # have ever been emitted — e.g. a single device (no mic) that
                # opens successfully but never produces a callback at all. That
                # case previously had NO diagnostic whatsoever: the old check
                # required emitted_bytes to cross a threshold, which never
                # happens if nothing is captured, so total silence with a
                # single device silently produced no feedback at all. Sent as a
                # non-fatal warning — it must never stop or block capture.
                if not reported_silence and now - start_time >= 5.0:
                    reported_silence = True
                    total_received = sum(received_samples)
                    log(f"[transcriber] 5s check — received_samples={received_samples} pending_pcm_bytes={len(pending_pcm)}")
                    if total_received == 0:
                        log("[transcriber] WARNING: zero samples received from any configured stream after 5s")
                        await ws.send_json({
                            "type": "warning",
                            "text": "No audio has been received at all after 5 seconds. This usually means "
                                    "macOS is silently blocking audio-input access for Transcriber even though "
                                    "it looks enabled. Try: System Settings → Privacy & Security → Microphone → "
                                    "toggle Transcriber off, back on, then restart the app. Recording continues.",
                        })
                    else:
                        tail = np.frombuffer(bytes(pending_pcm[-16000 * 2:]), dtype=np.int16).astype(np.float32) / 32768.0
                        peak = float(np.max(np.abs(tail))) if tail.size else 0.0
                        log(f"[transcriber] capture peak (5s check): {peak:.5f}")
                        if peak < 0.001:
                            log("[transcriber] NOTE: captured audio is silent so far")
                            await ws.send_json({
                                "type": "warning",
                                "text": "No sound detected yet. If recording meeting audio, make sure something "
                                        "is actually playing through your loopback device. Recording continues.",
                            })

                if now - last_preview >= 3.0 and not previewing and pending_pcm:
                    asyncio.create_task(_run_preview())
                    last_preview = now
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log(f"[transcriber] capture loop error: {exc}")
        finally:
            for s in streams:
                try:
                    s.stop()
                    s.close()
                except Exception:
                    pass
            log(f"[transcriber] capture stopped — {stats['emitted_bytes']} bytes emitted")

    async def _stop_capture():
        nonlocal _capture_task
        if _capture_task and not _capture_task.done():
            _capture_stop.set()
            try:
                await asyncio.wait_for(_capture_task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                _capture_task.cancel()
        _capture_task = None

    try:
        while True:
            message = await ws.receive()

            if message["type"] == "websocket.disconnect":
                break

            if "bytes" in message and message["bytes"]:
                # Browser mode: client sends raw PCM binary frames
                activity_seq += 1
                data = message["bytes"]
                pending_pcm.extend(data)
                if save_wav:
                    full_pcm.extend(data)

                if VERBOSE:
                    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
                    label = "near-silent" if peak < 0.001 else f"peak={peak:.4f}"
                    log(f"[transcriber] received {len(data)} bytes — {label}")

                if not previewing:
                    asyncio.create_task(_run_preview())

            elif "text" in message:
                cmd = message["text"]

                if cmd.startswith("{"):
                    try:
                        cfg = json.loads(cmd)
                        if cfg.get("type") == "config":
                            save_wav = bool(cfg.get("save_wav", False))
                            log(f"[transcriber] config: save_wav={save_wav}")
                        elif cfg.get("type") == "start":
                            # Desktop / pywebview mode: capture audio in Python
                            activity_seq += 1
                            log(f"[transcriber] received start: meeting_device={cfg.get('meeting_device')!r} mic_device={cfg.get('mic_device')!r}")
                            await _stop_capture()
                            _capture_task = asyncio.create_task(
                                _python_capture(
                                    cfg.get("meeting_device", ""),
                                    cfg.get("mic_device", ""),
                                )
                            )
                    except Exception as exc:
                        log(f"[transcriber] malformed control message ignored: {cmd!r} ({exc})")

                elif cmd == "SAVE":
                    # A SAVE that arrives with the exact same activity count as the
                    # last SAVE means nothing happened in between — e.g. two "SAVE"
                    # frames delivered back-to-back from one client action (proven
                    # to happen: they're processed one after another, not
                    # concurrently, so a plain in-flight flag doesn't catch this).
                    # Answer with the previous response instead of writing a second
                    # file for a session that hasn't changed.
                    if last_save is not None and last_save[0] == activity_seq:
                        log("[transcriber] duplicate SAVE ignored — no activity since the last save")
                        await ws.send_json(last_save[1])
                        continue

                    await _stop_capture()

                    # Millisecond resolution, not just seconds — two SAVEs completing
                    # within the same wall-clock second (e.g. rapid testing) would
                    # otherwise collide on the same filename and silently overwrite
                    # each other.
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")[:-3]

                    if save_wav and full_pcm:
                        wav_path = SAVE_DIR / f"transcript_{timestamp}.wav"
                        try:
                            _write_wav(bytes(full_pcm), wav_path)
                            if VERBOSE:
                                log(f"[transcriber] WAV saved: {wav_path}  ({len(full_pcm)} bytes, ~{len(full_pcm)/32000:.1f}s)")
                        except Exception as exc:
                            log(f"[transcriber] WAV write failed: {exc}")

                    all_segments = list(completed_segments)

                    if pending_pcm:
                        to_transcribe = overlap_pcm + bytes(pending_pcm)
                        skip_secs = len(overlap_pcm) / 32000.0
                        if VERBOSE:
                            log(f"[transcriber] SAVE: {len(pending_pcm)/32000:.0f}s tail + {len(completed_segments)} segments")
                        try:
                            loop = asyncio.get_running_loop()
                            tail_text = await loop.run_in_executor(
                                None, transcribe_pcm, to_transcribe, 16000, skip_secs
                            )
                            if tail_text:
                                all_segments.append(tail_text)
                        except Exception as exc:
                            log(f"[transcriber] save tail error: {exc}")
                            await ws.send_json({"type": "error", "text": f"Save failed: {exc}"})
                            _reset_session()
                            continue
                    elif VERBOSE:
                        log(f"[transcriber] SAVE: {len(completed_segments)} segments, no pending tail")

                    final_text = " ".join(all_segments)
                    save_path = SAVE_DIR / f"transcript_{timestamp}.txt"

                    # Summarization is a nice-to-have layer on top of a working save —
                    # its failure must never prevent the transcript itself from being
                    # written, so any error here just falls back to transcript-only.
                    document = final_text
                    if final_text:
                        await ws.send_json({"type": "status", "text": "Generating summary..."})
                        try:
                            loop = asyncio.get_running_loop()
                            summary = await loop.run_in_executor(
                                None, summarize_transcript, final_text
                            )
                            if summary:
                                document = f"Summary:\n{summary}\n\nTranscript:\n{final_text}"
                        except Exception as exc:
                            log(f"[transcriber] summarization failed: {type(exc).__name__}: {exc}")

                    save_path.write_text(document, encoding="utf-8")
                    response = {
                        "type": "saved",
                        "path": str(save_path),
                        "text": final_text,
                    }
                    await ws.send_json(response)
                    last_save = (activity_seq, response)
                    _reset_session()

                elif cmd == "CANCEL":
                    activity_seq += 1
                    await _stop_capture()
                    _reset_session()
                    await ws.send_json({"type": "cancelled"})

    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as exc:
        log(f"[transcriber] websocket handler error: {exc}")
    finally:
        await _stop_capture()
