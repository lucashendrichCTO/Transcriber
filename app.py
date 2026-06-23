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

# Prefer Desktop; fall back to home directory if Desktop doesn't exist
_desktop = Path.home() / "Desktop"
SAVE_DIR = _desktop if _desktop.exists() else Path.home()

# Set DEBUG_WAV=1 to dump a .wav alongside each transcript for audio inspection
DEBUG_WAV = os.environ.get("DEBUG_WAV", "1") == "1"

app.mount("/static", StaticFiles(directory="static"), name="static")


def _write_debug_wav(pcm_bytes: bytes, path: Path, sample_rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    # Raw 16-bit mono PCM bytes accumulated for the current recording session
    pcm = bytearray()
    # Avoid piling up live-preview passes on the CPU as the buffer grows
    previewing = False

    try:
        while True:
            message = await ws.receive()

            # Client closed the connection
            if message["type"] == "websocket.disconnect":
                break

            if "bytes" in message and message["bytes"]:
                pcm.extend(message["bytes"])

                # Skip this live preview if a previous one is still running
                if previewing:
                    continue
                previewing = True
                try:
                    loop = asyncio.get_event_loop()
                    snapshot = bytes(pcm)
                    transcript = await loop.run_in_executor(None, transcribe_pcm, snapshot)
                    await ws.send_json({"type": "transcript", "text": transcript})
                except Exception as exc:
                    print(f"[transcriber] live preview error: {exc}")
                    await ws.send_json({"type": "error", "text": f"Preview failed: {exc}"})
                finally:
                    previewing = False

            elif "text" in message:
                cmd = message["text"]

                if cmd == "SAVE":
                    if pcm:
                        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
                        pcm_snapshot = bytes(pcm)

                        if DEBUG_WAV:
                            wav_path = SAVE_DIR / f"transcript_{timestamp}_debug.wav"
                            try:
                                _write_debug_wav(pcm_snapshot, wav_path)
                                print(f"[transcriber] debug WAV saved: {wav_path}  ({len(pcm_snapshot)} bytes, ~{len(pcm_snapshot)/32000:.1f}s)")
                            except Exception as exc:
                                print(f"[transcriber] debug WAV write failed: {exc}")

                        try:
                            loop = asyncio.get_event_loop()
                            final_text = await loop.run_in_executor(
                                None, transcribe_pcm, pcm_snapshot
                            )
                            save_path = SAVE_DIR / f"transcript_{timestamp}.txt"
                            save_path.write_text(final_text, encoding="utf-8")
                            await ws.send_json({
                                "type": "saved",
                                "path": str(save_path),
                                "text": final_text,
                            })
                        except Exception as exc:
                            print(f"[transcriber] save error: {exc}")
                            await ws.send_json({"type": "error", "text": f"Save failed: {exc}"})
                    else:
                        await ws.send_json({"type": "error", "text": "No audio recorded."})

                    pcm = bytearray()

                elif cmd == "CANCEL":
                    pcm = bytearray()
                    await ws.send_json({"type": "cancelled"})

    except (WebSocketDisconnect, RuntimeError):
        # RuntimeError is raised by Starlette if the client disconnects abruptly
        pass
    except Exception as exc:
        print(f"[transcriber] websocket handler error: {exc}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8765, reload=False)
