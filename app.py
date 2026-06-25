import asyncio
import datetime
import os
import wave
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from transcriber import transcribe_pcm

app = FastAPI()

_desktop = Path.home() / "Desktop"
SAVE_DIR = _desktop if _desktop.exists() else Path.home()

DEBUG_WAV = os.environ.get("DEBUG_WAV", "1") == "1"

# 30-second chunks at 16 kHz / 16-bit mono = 960,000 bytes
CHUNK_BYTES = 30 * 16000 * 2
# 2-second overlap prepended to each chunk so Whisper has sentence context
OVERLAP_BYTES = 2 * 16000 * 2

app.mount("/static", StaticFiles(directory="static"), name="static")


def _write_debug_wav(pcm_bytes: bytes, path: Path, sample_rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    # PCM received since the last committed chunk
    pending_pcm: bytearray = bytearray()
    # Last 2s of the most recently committed chunk — prepended for context
    overlap_pcm: bytes = b""
    # Transcribed text from each committed 30s chunk
    completed_segments: list[str] = []
    # Full session PCM kept only for the debug WAV
    full_pcm: bytearray = bytearray() if DEBUG_WAV else None

    previewing = False

    try:
        while True:
            message = await ws.receive()

            if message["type"] == "websocket.disconnect":
                break

            if "bytes" in message and message["bytes"]:
                data = message["bytes"]
                pending_pcm.extend(data)
                if DEBUG_WAV:
                    full_pcm.extend(data)

                if previewing:
                    continue
                previewing = True

                loop = asyncio.get_running_loop()
                try:
                    if len(pending_pcm) >= CHUNK_BYTES:
                        # --- commit this chunk ---
                        to_transcribe = overlap_pcm + bytes(pending_pcm)
                        skip_secs = len(overlap_pcm) / 32000.0
                        new_overlap = bytes(pending_pcm[-OVERLAP_BYTES:])
                        pending_pcm = bytearray()

                        duration_s = len(to_transcribe) / 32000.0
                        print(f"[transcriber] committing chunk ({duration_s:.0f}s, skip {skip_secs:.1f}s overlap)")

                        text = await loop.run_in_executor(
                            None, transcribe_pcm, to_transcribe, 16000, skip_secs
                        )
                        if text:
                            completed_segments.append(text)
                        overlap_pcm = new_overlap

                        preview = " ".join(completed_segments)
                    else:
                        # --- live preview of the current accumulating chunk ---
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

            elif "text" in message:
                cmd = message["text"]

                if cmd == "SAVE":
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")

                    if DEBUG_WAV and full_pcm:
                        wav_path = SAVE_DIR / f"transcript_{timestamp}_debug.wav"
                        try:
                            _write_debug_wav(bytes(full_pcm), wav_path)
                            print(f"[transcriber] debug WAV saved: {wav_path}  ({len(full_pcm)} bytes, ~{len(full_pcm)/32000:.1f}s)")
                        except Exception as exc:
                            print(f"[transcriber] debug WAV write failed: {exc}")

                    all_segments = list(completed_segments)

                    if pending_pcm:
                        to_transcribe = overlap_pcm + bytes(pending_pcm)
                        skip_secs = len(overlap_pcm) / 32000.0
                        tail_secs = len(pending_pcm) / 32000.0
                        print(f"[transcriber] SAVE: transcribing {tail_secs:.0f}s tail + {len(completed_segments)} committed segments")
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
                            pending_pcm = bytearray()
                            overlap_pcm = b""
                            completed_segments = []
                            if DEBUG_WAV:
                                full_pcm = bytearray()
                            continue
                    else:
                        print(f"[transcriber] SAVE: {len(completed_segments)} committed segments, no pending tail")

                    final_text = " ".join(all_segments)
                    save_path = SAVE_DIR / f"transcript_{timestamp}.txt"
                    save_path.write_text(final_text, encoding="utf-8")
                    await ws.send_json({
                        "type": "saved",
                        "path": str(save_path),
                        "text": final_text,
                    })

                    # Reset for next session
                    pending_pcm = bytearray()
                    overlap_pcm = b""
                    completed_segments = []
                    if DEBUG_WAV:
                        full_pcm = bytearray()

                elif cmd == "CANCEL":
                    pending_pcm = bytearray()
                    overlap_pcm = b""
                    completed_segments = []
                    if DEBUG_WAV:
                        full_pcm = bytearray()
                    await ws.send_json({"type": "cancelled"})

    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as exc:
        print(f"[transcriber] websocket handler error: {exc}")
