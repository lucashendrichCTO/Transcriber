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


# Keep old name as an alias so existing test_wav.py imports continue to work
_write_debug_wav = _write_wav


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
    return JSONResponse({"devices": list_input_devices()})


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
        nonlocal previewing, pending_pcm, overlap_pcm, completed_segments
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
                    print(f"[transcriber] committing chunk ({len(to_transcribe)/32000:.0f}s)")
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
            print(f"[transcriber] preview error: {exc}")
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

        Per-stream float32 accumulators are mutated only on the event-loop thread
        (callbacks marshal frames via call_soon_threadsafe), so no locks are needed.
        """
        loop = asyncio.get_running_loop()
        _capture_stop.clear()

        # Distinct input streams to capture. Dedupe so selecting the same device
        # for both "meeting" and "mic" doesn't double it.
        devices: list[str] = [meeting_device]
        if mic_device and mic_device != meeting_device:
            devices.append(mic_device)

        accums: list[np.ndarray] = [np.zeros(0, dtype=np.float32) for _ in devices]
        # Bound clock drift between independent streams: never let one buffer get
        # more than ~2 s ahead of the slowest one (drop the oldest excess instead).
        MAX_BACKLOG = 2 * 16000
        stats = {"emitted_bytes": 0}

        def _ingest(idx: int, mono: np.ndarray) -> None:
            accums[idx] = np.concatenate((accums[idx], mono))
            if accums[idx].size > MAX_BACKLOG:
                accums[idx] = accums[idx][-MAX_BACKLOG:]
            # Emit only the span all streams have in common, summed (mixed).
            ready = min(a.size for a in accums)
            if ready <= 0:
                return
            mixed = accums[0][:ready].astype(np.float32, copy=True)
            for a in accums[1:]:
                mixed += a[:ready]
            for i in range(len(accums)):
                accums[i] = accums[i][ready:]
            np.clip(mixed, -1.0, 1.0, out=mixed)
            pcm = (mixed * 32767.0).astype("<i2").tobytes()
            pending_pcm.extend(pcm)
            if save_wav:
                full_pcm.extend(pcm)
            stats["emitted_bytes"] += len(pcm)

        def _make_cb(idx: int):
            def _cb(indata, frames, time_info, status):
                # Copy off PortAudio's reused buffer; mix down to mono (first channel).
                mono = np.array(indata[:, 0], dtype=np.float32)
                loop.call_soon_threadsafe(_ingest, idx, mono)
            return _cb

        streams: list = []
        try:
            for idx, dev in enumerate(devices):
                streams.append(open_input_stream(dev, _make_cb(idx)))
            for s in streams:
                s.start()
            print(f"[transcriber] Python capture started — devices={devices} streams={len(streams)}")
        except Exception as exc:
            print(f"[transcriber] capture init error: {exc}")
            await ws.send_json({"type": "error", "text": f"Audio capture failed: {exc}"})
            return

        last_preview = loop.time()
        reported_silence = False
        try:
            while not _capture_stop.is_set():
                await asyncio.sleep(0.1)

                # Warn once if audio looks silent after ~5s of captured audio.
                if not reported_silence and stats["emitted_bytes"] >= 5 * 16000 * 2:
                    tail = np.frombuffer(bytes(pending_pcm[-16000 * 2:]), dtype=np.int16).astype(np.float32) / 32768.0
                    peak = float(np.max(np.abs(tail))) if tail.size else 0.0
                    print(f"[transcriber] capture peak (5s check): {peak:.5f}")
                    if peak < 0.001:
                        print("[transcriber] WARNING: audio is silent — check mic permission in System Settings → Privacy & Security → Microphone")
                        await ws.send_json({"type": "error", "text": "Audio is silent — grant microphone access to Transcriber in System Settings → Privacy & Security → Microphone, then restart."})
                    reported_silence = True

                now = loop.time()
                if now - last_preview >= 3.0 and not previewing and pending_pcm:
                    asyncio.create_task(_run_preview())
                    last_preview = now
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            print(f"[transcriber] capture loop error: {exc}")
        finally:
            for s in streams:
                try:
                    s.stop()
                    s.close()
                except Exception:
                    pass
            print(f"[transcriber] capture stopped — {stats['emitted_bytes']} bytes emitted")

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
                data = message["bytes"]
                pending_pcm.extend(data)
                if save_wav:
                    full_pcm.extend(data)

                if VERBOSE:
                    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
                    label = "near-silent" if peak < 0.001 else f"peak={peak:.4f}"
                    print(f"[transcriber] received {len(data)} bytes — {label}")

                if not previewing:
                    asyncio.create_task(_run_preview())

            elif "text" in message:
                cmd = message["text"]

                if cmd.startswith("{"):
                    try:
                        cfg = json.loads(cmd)
                        if cfg.get("type") == "config":
                            save_wav = bool(cfg.get("save_wav", False))
                            if VERBOSE:
                                print(f"[transcriber] config: save_wav={save_wav}")
                        elif cfg.get("type") == "start":
                            # Desktop / pywebview mode: capture audio in Python
                            await _stop_capture()
                            _capture_task = asyncio.create_task(
                                _python_capture(
                                    cfg.get("meeting_device", ""),
                                    cfg.get("mic_device", ""),
                                )
                            )
                            if VERBOSE:
                                print(f"[transcriber] Python capture started: meeting={cfg.get('meeting_device')!r}")
                    except Exception:
                        pass

                elif cmd == "SAVE":
                    await _stop_capture()

                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")

                    if save_wav and full_pcm:
                        wav_path = SAVE_DIR / f"transcript_{timestamp}.wav"
                        try:
                            _write_wav(bytes(full_pcm), wav_path)
                            if VERBOSE:
                                print(f"[transcriber] WAV saved: {wav_path}  ({len(full_pcm)} bytes, ~{len(full_pcm)/32000:.1f}s)")
                        except Exception as exc:
                            print(f"[transcriber] WAV write failed: {exc}")

                    all_segments = list(completed_segments)

                    if pending_pcm:
                        to_transcribe = overlap_pcm + bytes(pending_pcm)
                        skip_secs = len(overlap_pcm) / 32000.0
                        if VERBOSE:
                            print(f"[transcriber] SAVE: {len(pending_pcm)/32000:.0f}s tail + {len(completed_segments)} segments")
                        try:
                            loop = asyncio.get_running_loop()
                            tail_text = await loop.run_in_executor(
                                None, transcribe_pcm, to_transcribe, 16000, skip_secs
                            )
                            if tail_text:
                                all_segments.append(tail_text)
                        except Exception as exc:
                            print(f"[transcriber] save tail error: {exc}")
                            await ws.send_json({"type": "error", "text": f"Save failed: {exc}"})
                            _reset_session()
                            continue
                    elif VERBOSE:
                        print(f"[transcriber] SAVE: {len(completed_segments)} segments, no pending tail")

                    final_text = " ".join(all_segments)
                    save_path = SAVE_DIR / f"transcript_{timestamp}.txt"
                    save_path.write_text(final_text, encoding="utf-8")
                    await ws.send_json({
                        "type": "saved",
                        "path": str(save_path),
                        "text": final_text,
                    })
                    _reset_session()

                elif cmd == "CANCEL":
                    await _stop_capture()
                    _reset_session()
                    await ws.send_json({"type": "cancelled"})

    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as exc:
        print(f"[transcriber] websocket handler error: {exc}")
    finally:
        await _stop_capture()
