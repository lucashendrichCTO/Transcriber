import asyncio
import datetime
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from transcriber import transcribe_webm, get_model

app = FastAPI()

SAVE_DIR = Path.home() / "Desktop"

# Eagerly load the model at startup so the first recording isn't slow
@app.on_event("startup")
async def startup():
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, get_model)


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    # Accumulate all audio chunks for the current recording session
    chunks: list[bytes] = []

    try:
        while True:
            message = await ws.receive()

            if "bytes" in message and message["bytes"]:
                chunk: bytes = message["bytes"]
                chunks.append(chunk)

                # Transcribe all accumulated audio so far for live preview
                combined = b"".join(chunks)
                loop = asyncio.get_event_loop()
                transcript = await loop.run_in_executor(None, transcribe_webm, combined)
                await ws.send_json({"type": "transcript", "text": transcript})

            elif "text" in message:
                cmd = message["text"]

                if cmd == "SAVE":
                    # Final transcription + save to Desktop
                    combined = b"".join(chunks)
                    if combined:
                        loop = asyncio.get_event_loop()
                        final_text = await loop.run_in_executor(None, transcribe_webm, combined)
                        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
                        save_path = SAVE_DIR / f"transcript_{timestamp}.txt"
                        save_path.write_text(final_text, encoding="utf-8")
                        await ws.send_json({
                            "type": "saved",
                            "path": str(save_path),
                            "text": final_text,
                        })
                    else:
                        await ws.send_json({"type": "error", "text": "No audio recorded."})

                    # Clear session state
                    chunks.clear()

                elif cmd == "CANCEL":
                    chunks.clear()
                    await ws.send_json({"type": "cancelled"})

    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8765, reload=False)
